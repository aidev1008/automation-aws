import sys
import asyncio

# THIS MUST BE FIRST!
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import os
import re
import logging
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from playwright.async_api import async_playwright
from dotenv import load_dotenv
import uvicorn
import boto3
from botocore.exceptions import ClientError
import tempfile

# Load environment variables
load_dotenv()

# Configure logging
log_level = os.getenv("LOG_LEVEL", "INFO").upper()
log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# Create logs directory if it doesn't exist
os.makedirs("logs", exist_ok=True)

# Create custom formatter to handle Unicode issues
class SafeFormatter(logging.Formatter):
    def format(self, record):
        # Remove emojis and replace with simple text
        if hasattr(record, 'msg'):
            safe_msg = str(record.msg)
            # Replace common emojis with text equivalents
            emoji_replacements = {
                '🚀': '[START]',
                '🌐': '[URL]',
                '🖥️': '[BROWSER]',
                '🔧': '[INIT]',
                '✅': '[SUCCESS]',
                '📋': '[NAVIGATE]',
                '🔍': '[SEARCH]',
                '👤': '[USERNAME]',
                '🔐': '[PASSWORD]',
                '🔄': '[SUBMIT]',
                '⏳': '[WAIT]',
                '📄': '[PAGE]',
                '🧭': '[NAVIGATION]',
                '🏁': '[FINAL]',
                '📸': '[SCREENSHOT]',
                '⚠️': '[WARNING]',
                '❌': '[ERROR]'
            }
            for emoji, replacement in emoji_replacements.items():
                safe_msg = safe_msg.replace(emoji, replacement)
            record.msg = safe_msg
        return super().format(record)

# Configure file handler with UTF-8 encoding
file_handler = logging.FileHandler(
    f"logs/automation_{datetime.now().strftime('%Y%m%d')}.log",
    encoding='utf-8'
)
file_handler.setFormatter(logging.Formatter(log_format))

# Configure console handler with safe formatter
console_handler = logging.StreamHandler()
console_handler.setFormatter(SafeFormatter(log_format))

# Configure logging
logging.basicConfig(
    level=getattr(logging, log_level),
    handlers=[file_handler, console_handler]
)

logger = logging.getLogger("PlaywrightAutomation")

# FastAPI app
app = FastAPI(title="Simple Login Automation", version="1.0.0")

# Diagnostics artifacts directory
os.makedirs(os.path.join("logs", "artifacts"), exist_ok=True)

# Pydantic model for login request
class LoginRequest(BaseModel):
    username: str
    password: str
    s3_filename: str  # Filename to fetch from S3
    url: Optional[str] = "https://lendly.catch-e.net.au/core/login.phpo?i=&user_login=ben.lazzaro&screen_width=1536&screen_height=960"

# Global browser instance
browser_instance = None

# S3 Configuration
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "fuel-invoices-receipt")
AWS_REGION = os.getenv("AWS_REGION", "ap-southeast-2")

def _get_s3_client():
    return boto3.client(
        's3',
        region_name=AWS_REGION,
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY")
    )

def resolve_s3_key(user_filename: str) -> Optional[str]:
    """
    Try to resolve a user-provided filename to an S3 object key in the bucket.

    Matching strategy (first hit wins):
    1) Exact key match
    2) Key ending with filename (basename match)
    3) Case-insensitive basename match
    4) First key that contains the filename as a substring

    Returns:
        The resolved key if found, otherwise None
    """
    try:
        s3_client = _get_s3_client()

        # 1) Exact key match (HEAD request is cheap)
        try:
            s3_client.head_object(Bucket=S3_BUCKET_NAME, Key=user_filename)
            return user_filename
        except ClientError:
            pass

        paginator = s3_client.get_paginator('list_objects_v2')
        page_iterator = paginator.paginate(Bucket=S3_BUCKET_NAME)

        target_lower = user_filename.lower()
        basename_lower = os.path.basename(user_filename).lower()

        exact_basename_key = None
        ci_basename_key = None
        contains_key = None

        for page in page_iterator:
            for obj in page.get('Contents', []):
                key = obj['Key']
                key_lower = key.lower()

                # 2) Key ending with filename (basename match)
                if key.endswith(user_filename):
                    return key

                # 3) Case-insensitive basename match
                if os.path.basename(key_lower) == basename_lower and ci_basename_key is None:
                    ci_basename_key = key

                # 4) Substring match (fallback)
                if target_lower in key_lower and contains_key is None:
                    contains_key = key

        if exact_basename_key:
            return exact_basename_key
        if ci_basename_key:
            return ci_basename_key
        if contains_key:
            return contains_key

        return None
    except Exception as e:
        logger.error(f"[S3] Failed to resolve key for '{user_filename}': {e}")
        return None

def download_file_from_s3(filename: str, local_path: str) -> bool:
    """
    Download a file from S3 bucket to local path
    
    Args:
        filename: Name of the file in S3 bucket
        local_path: Local path where file should be saved
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        logger.info(f"[S3] Attempting to download file: {filename} from bucket: {S3_BUCKET_NAME}")

        s3_client = _get_s3_client()

        # Download file from S3
        s3_client.download_file(S3_BUCKET_NAME, filename, local_path)
        logger.info(f"[S3] File downloaded successfully to: {local_path}")
        return True

    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == '404':
            logger.error(f"[S3] File not found in bucket: {filename}")
        else:
            logger.error(f"[S3] Error downloading file: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"[S3] Unexpected error: {str(e)}")
        return False

def prepare_local_file_from_s3(requested_filename: str) -> Optional[str]:
    """
    Resolve a filename to an S3 key and download it to a temp file.
    Returns the local temp file path if successful, else None.
    """
    if not requested_filename:
        return None

    key = resolve_s3_key(requested_filename)
    if not key:
        logger.warning(f"[S3] No matching object found for '{requested_filename}' in bucket '{S3_BUCKET_NAME}'")
        return None

    temp_dir = tempfile.gettempdir()
    local_path = os.path.join(temp_dir, os.path.basename(key))
    if download_file_from_s3(key, local_path):
        return local_path
    return None

async def select_calns_in_popup(popup_page, navigation_steps) -> bool:
    """
    Robustly select CALNS inside the popup page. Searches across the popup root
    and all its frames, with multiple selector strategies and waits. Captures
    artifacts if not found for easier diagnostics.

    Returns True if a click/selection was made, False otherwise.
    """
    try:
        try:
            await popup_page.bring_to_front()
        except Exception:
            pass

        # Give popup time for any XHR-driven content
        try:
            await popup_page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass

        # Wait until CALNS text appears anywhere in popup (root or frames)
        async def has_calns():
            try:
                if await popup_page.locator('text=/\\bCALNS\\b/i').count() > 0:
                    return True
                for fr in popup_page.frames:
                    try:
                        if await fr.locator('text=/\\bCALNS\\b/i').count() > 0:
                            return True
                    except Exception:
                        continue
            except Exception:
                pass
            return False

        # Poll for up to 7 seconds
        end_wait_ms = 7000
        step = 250
        waited = 0
        while waited < end_wait_ms:
            if await has_calns():
                break
            await popup_page.wait_for_timeout(step)
            waited += step

        # Candidate selectors to try
        selector_sets = [
            ['role=link[name=/^\\s*CALNS\\s*$/i]'],
            ['text=/\\bCALNS\\b/i'],
            ['a:has-text("CALNS")'],
            ['td:has-text("CALNS")', 'tr:has-text("CALNS")'],
            ['xpath=//a[normalize-space(.)="CALNS"]',
             'xpath=//tr[.//text()[contains(.,"CALNS")]]',
             'xpath=//td[.//text()[contains(.,"CALNS")]]']
        ]

        contexts = [popup_page] + popup_page.frames
        for sel_group in selector_sets:
            for ctx in contexts:
                for sel in sel_group:
                    try:
                        loc = ctx.locator(sel).first
                        if await loc.count() == 0:
                            continue
                        await loc.scroll_into_view_if_needed()
                        try:
                            await loc.click()
                        except Exception:
                            # Try dblclick, then force
                            try:
                                await loc.dblclick()
                            except Exception:
                                await loc.click(force=True)
                        navigation_steps.append(f"Selected CALNS in popup using selector: {sel}")
                        return True
                    except Exception:
                        continue

        # As a last fallback, try to click nearest clickable ancestor via JS
        try:
            clicked = await popup_page.evaluate("""
                () => {
                  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT, null);
                  const matches = [];
                  while (walker.nextNode()) {
                    const el = walker.currentNode;
                    if (!el || !el.innerText) continue;
                    if (/\bCALNS\b/i.test(el.innerText)) {
                      matches.push(el);
                    }
                  }
                  for (const el of matches) {
                    let node = el;
                    for (let i=0; i<4 && node; i++) {
                      if (node.tagName === 'A' || node.onclick || node.getAttribute('href')) {
                        node.click();
                        return true;
                      }
                      node = node.parentElement;
                    }
                  }
                  return false;
                }
            """)
            if clicked:
                navigation_steps.append("Selected CALNS in popup via JS fallback")
                return True
        except Exception:
            pass

        # Save artifacts for debugging
        try:
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            html_path = os.path.join('logs', 'artifacts', f'popup_{ts}.html')
            png_path = os.path.join('logs', 'artifacts', f'popup_{ts}.png')
            content = await popup_page.content()
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(content)
            await popup_page.screenshot(path=png_path, full_page=True)
            navigation_steps.append(f"Saved popup artifacts: {html_path}, {png_path}")
        except Exception:
            pass

        return False
    except Exception as e:
        navigation_steps.append(f"Popup CALNS selection error: {e}")
        return False

@app.post("/login")
async def login(credentials: LoginRequest):
    """Perform automated login with provided credentials"""
    global browser_instance
    
    logger.info(f" Login automation started for user: {credentials.username}")
    logger.info(f"🌐 Target URL: {credentials.url}")
    
    try:
        # Get headless setting from environment
        headless = os.getenv("HEADLESS", "true").lower() == "true"
        logger.info(f"🖥️  Browser mode: {'Headless' if headless else 'Visible'}")
        
        # Start playwright
        logger.info("🔧 Initializing Playwright browser...")
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(headless=headless)
        context = await browser.new_context(
            viewport={"width": 1536, "height": 960}
        )
        page = await context.new_page()
        logger.info("✅ Browser initialized successfully")
        
        # Navigate to the login URL
        logger.info("📋 Navigating to login page...")
        await page.goto(credentials.url)
        await page.wait_for_load_state("networkidle")
        logger.info("✅ Login page loaded successfully")
        
        # Try to find and fill login form
        logger.info("🔍 Searching for login form elements...")
        
        # Common username field selectors
        username_selectors = [
            "input[name='username']",
            "input[name='user']", 
            "input[name='email']",
            "input[name='login']",
            "input[type='text']",
            "#username",
            "#user",
            "#email"
        ]
        
        # Common password field selectors
        password_selectors = [
            "input[name='password']",
            "input[type='password']",
            "#password"
        ]
        
        # Submit button selectors
        submit_selectors = [
            "button[type='submit']",
            "input[type='submit']",
            "button:has-text('Login')",
            "button:has-text('Sign in')",
            "input[value*='Login']"
        ]
        
        # Fill username
        username_filled = False
        logger.info("👤 Attempting to fill username field...")
        for selector in username_selectors:
            try:
                element = await page.query_selector(selector)
                if element:
                    await element.fill(credentials.username)
                    username_filled = True
                    logger.info(f"✅ Username filled using selector: {selector}")
                    break
            except:
                continue
        
        if not username_filled:
            logger.warning("⚠️  Username field not found")
        
        # Fill password
        password_filled = False
        logger.info("🔐 Attempting to fill password field...")
        for selector in password_selectors:
            try:
                element = await page.query_selector(selector)
                if element:
                    await element.fill(credentials.password)
                    password_filled = True
                    logger.info(f"✅ Password filled using selector: {selector}")
                    break
            except:
                continue
        
        if not password_filled:
            logger.warning("⚠️  Password field not found")
        
        # Submit form
        submit_clicked = False
        logger.info("🔄 Attempting to submit login form...")
        for selector in submit_selectors:
            try:
                element = await page.query_selector(selector)
                if element:
                    await element.click()
                    submit_clicked = True
                    logger.info(f"✅ Form submitted using selector: {selector}")
                    break
            except:
                continue
        
        if not submit_clicked:
            logger.warning("⚠️  Submit button not found")
        
        # Wait for response
        logger.info("⏳ Waiting for page to load after login...")
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
            logger.info("✅ Page loaded after login")
        except:
            logger.warning("⚠️  Page load timeout, continuing anyway")
        
        # Get final page info
        final_url = page.url
        page_title = await page.title()
        logger.info(f"📄 Current page: {page_title} - {final_url}")
        
        # If provided, pre-resolve and download S3 file for upload later
        upload_file_local_path: Optional[str] = None
        if credentials.s3_filename:
            logger.info(f"[S3] Resolving provided filename: {credentials.s3_filename}")
            upload_file_local_path = prepare_local_file_from_s3(credentials.s3_filename)
            if upload_file_local_path:
                logger.info(f"[S3] File ready for upload at: {upload_file_local_path}")
            else:
                logger.warning("[S3] Could not prepare file for upload; proceeding without upload")

        # Navigation after successful login
        logger.info("🧭 Starting navigation sequence...")
        navigation_success = False
        navigation_steps = []
        
        try:
            # Step 1: Hover over Fleet menu
            fleet_element = await page.query_selector('td[id="HM_Menu1_top"]')
            if not fleet_element:
                # Try alternative selectors for Fleet
                fleet_selectors = [
                    'td:has-text("Fleet")',
                    '[onmouseover*="HM_Menu1"]',
                    '.top_menu_off:has-text("Fleet")'
                ]
                for selector in fleet_selectors:
                    fleet_element = await page.query_selector(selector)
                    if fleet_element:
                        break
            
            if fleet_element:
                await fleet_element.hover()
                await page.wait_for_timeout(1000)  # Wait for dropdown to appear
                navigation_steps.append("Fleet menu hovered")
                
                # Step 2: Hover over Card Services in the dropdown
                card_services_selectors = [
                    'text="Card Services"',
                    'td:has-text("Card Services")',
                    '[onmouseover]:has-text("Card Services")'
                ]
                
                card_services_element = None
                for selector in card_services_selectors:
                    try:
                        card_services_element = await page.query_selector(selector)
                        if card_services_element:
                            break
                    except:
                        continue
                
                if card_services_element:
                    await card_services_element.hover()
                    await page.wait_for_timeout(1000)  # Wait for submenu to appear
                    navigation_steps.append("Card Services submenu hovered")
                    
                    # Step 3: Click on Transactions
                    transaction_selectors = [
                        'text="Transactions"',
                        'td:has-text("Transactions")',
                        'a:has-text("Transactions")'
                    ]
                    
                    transaction_element = None
                    for selector in transaction_selectors:
                        try:
                            transaction_element = await page.query_selector(selector)
                            if transaction_element:
                                break
                        except:
                            continue
                    
                    if transaction_element:
                        await transaction_element.click()
                        await page.wait_for_load_state("networkidle", timeout=10000)
                        navigation_steps.append("Transactions clicked")
                        
                        # Step 4: Click Import button on transactions page
                        import_button_selectors = [
                            'input[name="button_import"]',
                            'input[id="button_import"]',
                            'input[value="Import"]',
                            '.formbutton[value="Import"]'
                        ]
                        
                        import_button_element = None
                        for selector in import_button_selectors:
                            try:
                                import_button_element = await page.query_selector(selector)
                                if import_button_element:
                                    break
                            except:
                                continue
                        
                        if import_button_element:
                            await import_button_element.click()
                            await page.wait_for_load_state("networkidle", timeout=10000)
                            navigation_steps.append("Import button clicked")
                            
                            # Step 5: Fill input field with "CALNS"
                            input_field_selectors = [
                                'input[name="fm_int_interface_code"]',
                                'input[id="fm_int_interface_code"]',
                                '.forminput.border_input[name="fm_int_interface_code"]'
                            ]
                            
                            input_field_element = None
                            for selector in input_field_selectors:
                                try:
                                    input_field_element = await page.query_selector(selector)
                                    if input_field_element:
                                        break
                                except:
                                    continue
                            
                            if input_field_element:
                                await input_field_element.fill("CALNS")
                                navigation_steps.append("Input field filled with 'CALNS'")

                                # Wait 2 seconds as requested
                                await page.wait_for_timeout(2000)
                                navigation_steps.append("Waited 2 seconds after input")
                                
                                # Step 6: Click search button and handle popup window
                                search_button_selectors = [
                                    'i.catch_e_icon_search',
                                    'i.catch-e-icon-lookingglass1',
                                    'i[title="Find"]',
                                    '.catch_e_icon_search',
                                    '.catch-e-icon-lookingglass1',
                                    'i[class*="catch_e_icon_search"]',
                                    'i[class*="lookingglass"]'
                                ]

                                search_button_element = None
                                for selector in search_button_selectors:
                                    try:
                                        search_button_element = await page.query_selector(selector)
                                        if search_button_element:
                                            break
                                    except:
                                        continue

                                if search_button_element:
                                    navigation_steps.append("Search button found")

                                    # Capture popup *window* before click
                                    popup_promise = page.wait_for_event("popup")
                                    await search_button_element.click()
                                    navigation_steps.append("Search button clicked")

                                    try:
                                        popup_page = await popup_promise
                                        await popup_page.wait_for_load_state("domcontentloaded")
                                        # Use robust selector routine to click CALNS
                                        calns_clicked = await select_calns_in_popup(popup_page, navigation_steps)

                                        # If we clicked an option, wait for popup to close
                                        if calns_clicked:
                                            try:
                                                await popup_page.wait_for_close(timeout=10000)
                                                navigation_steps.append("Popup closed after selecting CALNS")
                                            except Exception:
                                                navigation_steps.append("Popup did not close automatically after selection")
                                        else:
                                            navigation_steps.append("CALNS option not found/clicked in popup; proceeding anyway")

                                        # Small delay to allow main page to update based on selection
                                        await page.wait_for_timeout(1500)

                                        # Try to detect if page has frames and find dropzone
                                        frames = page.frames
                                        navigation_steps.append(f"After popup close, page has {len(frames)} frames")

                                        dropzone_frame = None
                                        for frame in frames:
                                            try:
                                                content = await frame.content()
                                                if "file-attachment-dropzone" in content:
                                                    dropzone_frame = frame
                                                    break
                                            except:
                                                continue

                                        if dropzone_frame:
                                            navigation_steps.append(f"Found dropzone inside frame: {dropzone_frame.url}")

                                            # Wait for the dropzone inside that frame
                                            try:
                                                await dropzone_frame.wait_for_selector('#file-attachment-dropzone', timeout=20000)
                                                
                                                # Click browse and attach file if available
                                                if upload_file_local_path and os.path.exists(upload_file_local_path):
                                                    try:
                                                        # Prefer direct file input if present
                                                        file_input = await dropzone_frame.query_selector('input[type="file"]')
                                                        if file_input:
                                                            await dropzone_frame.set_input_files('input[type="file"]', upload_file_local_path)
                                                            navigation_steps.append(f"File uploaded via set_input_files: {os.path.basename(upload_file_local_path)}")
                                                            await page.wait_for_timeout(2000)
                                                            navigation_steps.append("Waited for file upload to process")
                                                        else:
                                                            # Fall back to page-level file chooser while clicking inside frame
                                                            async with page.expect_file_chooser() as fc_info:
                                                                await dropzone_frame.click('#file-attachment-dropzone a')
                                                            file_chooser = await fc_info.value
                                                            await file_chooser.set_files(upload_file_local_path)
                                                            navigation_steps.append(f"File uploaded via file chooser: {os.path.basename(upload_file_local_path)}")
                                                            await page.wait_for_timeout(2000)
                                                            navigation_steps.append("Waited for file upload to process")
                                                    except Exception as upload_error:
                                                        navigation_steps.append(f"File upload error: {str(upload_error)}")
                                                    finally:
                                                        try:
                                                            if os.path.exists(upload_file_local_path):
                                                                os.remove(upload_file_local_path)
                                                                navigation_steps.append("Temporary file cleaned up")
                                                        except:
                                                            pass
                                                else:
                                                    # No file provided; try opening browse to indicate reachability
                                                    try:
                                                        await dropzone_frame.click('#file-attachment-dropzone a')
                                                        navigation_steps.append("Clicked 'browse' link inside dropzone frame (no file upload)")
                                                    except Exception:
                                                        navigation_steps.append("Dropzone link not clickable without file")
                                                    
                                            except Exception as browse_error:
                                                navigation_steps.append(f"Failed to click 'browse' link inside frame: {browse_error}")

                                        else:
                                            # Fallback — maybe dropzone is in main DOM, but just delayed
                                            try:
                                                await page.wait_for_selector('#file-attachment-dropzone', timeout=20000)
                                                
                                                # Click browse and attach file if available (main page)
                                                if upload_file_local_path and os.path.exists(upload_file_local_path):
                                                    try:
                                                        # Prefer direct file input if present
                                                        file_input = await page.query_selector('input[type="file"]')
                                                        if file_input:
                                                            await page.set_input_files('input[type="file"]', upload_file_local_path)
                                                            navigation_steps.append(f"File uploaded via set_input_files: {os.path.basename(upload_file_local_path)}")
                                                            await page.wait_for_timeout(2000)
                                                            navigation_steps.append("Waited for file upload to process")
                                                        else:
                                                            async with page.expect_file_chooser() as fc_info:
                                                                await page.click('#file-attachment-dropzone a')
                                                            file_chooser = await fc_info.value
                                                            await file_chooser.set_files(upload_file_local_path)
                                                            navigation_steps.append(f"File uploaded via file chooser: {os.path.basename(upload_file_local_path)}")
                                                            await page.wait_for_timeout(2000)
                                                            navigation_steps.append("Waited for file upload to process")
                                                    except Exception as upload_error:
                                                        navigation_steps.append(f"File upload error: {str(upload_error)}")
                                                    finally:
                                                        try:
                                                            if os.path.exists(upload_file_local_path):
                                                                os.remove(upload_file_local_path)
                                                                navigation_steps.append("Temporary file cleaned up")
                                                        except:
                                                            pass
                                                else:
                                                    await page.click('#file-attachment-dropzone a')
                                                    navigation_steps.append("Clicked 'browse' link successfully on main page (no file upload)")
                                                    
                                            except Exception as browse_error:
                                                navigation_steps.append(f"Browse link not found after waiting: {browse_error}")
                                        
                                        # Wait 3 seconds after clicking browse link
                                        await page.wait_for_timeout(3000)
                                        navigation_steps.append("Waited 3 seconds after browse link click")

                                    except Exception as popup_error:
                                        navigation_steps.append(f"Popup handling failed: {popup_error}")

                                else:
                                    navigation_steps.append("Search button not found")
                            else:
                                navigation_steps.append("Input field not found")
                        else:
                            navigation_steps.append("Import button not found")
                    else:
                        navigation_steps.append("Transactions element not found")
                else:
                    navigation_steps.append("Card Services element not found")
            else:
                navigation_steps.append("Fleet element not found")
                
        except Exception as nav_error:
            navigation_steps.append(f"Navigation error: {str(nav_error)}")
        
        # Update final page info after navigation
        final_url = page.url
        page_title = await page.title()
        logger.info(f"🏁 Final page: {page_title} - {final_url}")
        
        # Close browser
        logger.info("🔄 Closing browser...")
        # await browser.close()
        # await playwright.stop()
        logger.info("✅ Automation completed successfully!")
        
        return {
            "success": True,
            "message": "Login and navigation completed",
            "data": {
                "username_filled": username_filled,
                "password_filled": password_filled,
                "submit_clicked": submit_clicked,
                "navigation_success": navigation_success,
                "navigation_steps": navigation_steps,
                "final_url": final_url,
                "page_title": page_title
            }
        }
        
    except Exception as e:
        logger.error(f"❌ Automation failed: {str(e)}")
        logger.exception("Full error traceback:")
        
        # Clean up on error
        try:
            if browser_instance:
                await browser_instance.close()
                logger.info("🔄 Browser cleaned up after error")
        except:
            logger.warning("⚠️  Failed to cleanup browser")
        
        return {
            "success": False,
            "message": f"Login failed: {str(e)}",
            "error": str(e)
        }


@app.get("/health")
async def health():
    """Health check"""
    return {"status": "healthy"}

if __name__ == "__main__":
    # Get configuration from environment or use defaults
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))
    
    logger.info("🚀 Starting Simple Login Automation API...")
    logger.info(f"📍 Server will run on: http://{host}:{port}")
    logger.info("📚 API Documentation: http://localhost:8000/docs")
    logger.info("\n💡 Example usage:")
    logger.info('curl -X POST "http://localhost:8000/login" \\')
    logger.info('     -H "Content-Type: application/json" \\')
    logger.info('     -d \'{"username": "your_username", "password": "your_password"}\'')
    logger.info("📝 Logs are being saved to: logs/automation_[date].log")
    
    uvicorn.run(app, host=host, port=port)