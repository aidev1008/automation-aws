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
from fastapi import FastAPI
from pydantic import BaseModel
from playwright.async_api import async_playwright
from dotenv import load_dotenv
import uvicorn
import boto3
from botocore.exceptions import ClientError
import tempfile
from web_selectors import (
    USERNAME_SELECTORS,
    PASSWORD_SELECTORS,
    SUBMIT_SELECTORS,
    FLEET_SELECTORS,
    CARD_SERVICES_SELECTORS,
    TRANSACTION_SELECTORS,
    IMPORT_BUTTON_SELECTORS,
    INTERFACE_CODE_INPUT_SELECTORS,
    SEARCH_BUTTON_SELECTORS,
    DROPZONE_SELECTOR,
    FILE_INPUT_SELECTOR,
    UPLOAD_BUTTON_SELECTORS,
    INVOICE_INPUT_SELECTORS,
    TOTAL_GROSS_SELECTOR,
    SAVE_BUTTON_SELECTORS,
    CHECK_BUTTON_SELECTORS,
    POST_BUTTON_SELECTORS,
    POST_BUTTON_ANY_SELECTORS,
    ABORT_BUTTON_SELECTORS,
)

load_dotenv()

log_level = os.getenv("LOG_LEVEL", "INFO").upper()
log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# Create logs directory if it doesn't exist
os.makedirs("logs", exist_ok=True)
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
    gross: str
    invoice_number: str
    url: Optional[str] = "https://lendly.catch-e.net.au/core/login.phpo?i=&user_login=ben.lazzaro&screen_width=1536&screen_height=960"

# Helper utilities
async def query_selector_any(page, selectors):
    for sel in selectors:
        try:
            el = await page.query_selector(sel)
            if el:
                return el, sel
        except Exception:
            continue
    return None, None


async def query_selector_any_in_page_or_frames(page, selectors):
    el, sel = await query_selector_any(page, selectors)
    if el:
        return el, sel, page
    for fr in page.frames:
        try:
            for s in selectors:
                try:
                    el = await fr.query_selector(s)
                    if el:
                        return el, s, fr
                except Exception:
                    continue
        except Exception:
            continue
    return None, None, None


async def click_first(page, selectors):
    el, sel, ctx = await query_selector_any_in_page_or_frames(page, selectors)
    if not el:
        return False, None
    try:
        await el.scroll_into_view_if_needed()
    except Exception:
        pass
    try:
        await el.click()
        return True, sel
    except Exception:
        try:
            await el.dblclick()
            return True, sel
        except Exception:
            try:
                await el.click(force=True)
                return True, sel
            except Exception:
                return False, sel


async def fill_first(page, selectors, value: str):
    el, sel, ctx = await query_selector_any_in_page_or_frames(page, selectors)
    if not el:
        return False, None
    try:
        await el.fill(value)
        return True, sel
    except Exception:
        return False, sel


def normalize_amount(s: str) -> Optional[str]:
    try:
        if s is None:
            return None
        v = str(s).strip().replace("\xa0", " ")
        v = v.replace(",", "").replace(" ", "")
        m = re.findall(r"[0-9]+(?:\.[0-9]{1,4})?", v)
        if not m:
            return None
        num = m[0]
        if "." in num:
            parts = num.split(".")
            decimals = (parts[1] + "00")[:2]
            return f"{int(parts[0])}.{decimals}"
        else:
            return f"{int(num)}.00"
    except Exception:
        return None


async def read_text(page, selector: str) -> Optional[str]:
    try:
        el = await page.query_selector(selector)
        if el:
            return await el.inner_text()
    except Exception:
        pass
    for fr in page.frames:
        try:
            el = await fr.query_selector(selector)
            if el:
                return await el.inner_text()
        except Exception:
            continue
    return None

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
    
    logger.info(f" Login automation started for user: {credentials.username}")
    logger.info(f"🌐 Target URL: {credentials.url}")
    logger.info(f"Request context: s3_filename={credentials.s3_filename}, gross='{credentials.gross}', invoice_number='{credentials.invoice_number}'")
    
    # init for cleanup
    playwright = None
    browser = None

    try:
        # Get headless setting from environment
        headless = os.getenv("HEADLESS", "true").lower() == "true"
        logger.info(f"🖥️  Browser mode: {'Headless' if headless else 'Visible'}")
        
        # Start playwright
        logger.info("🔧 Initializing Playwright browser...")
        playwright = await async_playwright().start()
        browser = await playwright.firefox.launch(headless=headless)
        # Use fullscreen viewport
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            screen={"width": 1920, "height": 1080}
        )
        logger.info("Viewport set to fullscreen (1920x1080)")
        page = await context.new_page()
        logger.info("✅ Browser initialized successfully")
        
        # Navigate to the login URL
        logger.info("📋 Navigating to login page...")
        await page.goto(credentials.url)
        await page.wait_for_load_state("networkidle")
        logger.info("✅ Login page loaded successfully")
        
        # Try to find and fill login form
        logger.info("🔍 Searching for login form elements...")

        # Fill username
        username_filled = False
        logger.info("👤 Attempting to fill username field...")
        ok, sel = await fill_first(page, USERNAME_SELECTORS, credentials.username)
        if ok:
            username_filled = True
            logger.info(f"✅ Username filled using selector: {sel}")
        
        if not username_filled:
            logger.warning("⚠️  Username field not found")
        
        # Fill password
        password_filled = False
        logger.info("🔐 Attempting to fill password field...")
        ok, sel = await fill_first(page, PASSWORD_SELECTORS, credentials.password)
        if ok:
            password_filled = True
            logger.info(f"✅ Password filled using selector: {sel}")
        
        if not password_filled:
            logger.warning("⚠️  Password field not found")
        
        # Submit form
        submit_clicked = False
        logger.info("🔄 Attempting to submit login form...")
        ok, sel = await click_first(page, SUBMIT_SELECTORS)
        if ok:
            submit_clicked = True
            logger.info(f"✅ Form submitted using selector: {sel}")
        
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
        
        # Resolve and download S3 file (required) — error if not found
        upload_file_local_path: Optional[str] = None
        logger.info(f"[S3] Resolving provided filename: {credentials.s3_filename}")
        upload_file_local_path = prepare_local_file_from_s3(credentials.s3_filename)
        if upload_file_local_path:
            logger.info(f"[S3] File ready for upload at: {upload_file_local_path}")
        else:
            logger.error(f"[S3] File not found in bucket or could not be downloaded: {credentials.s3_filename}")
            return {
                "success": False,
                "status": "error",
                "error": {
                    "key": "s3_not_found",
                    "message": f"File not found in S3 or no match: {credentials.s3_filename}"
                },
                "data": {
                    "provided_filename": credentials.s3_filename
                }
            }

        # Navigation after successful login
        logger.info("🧭 Starting navigation sequence...")
        navigation_success = False
        navigation_steps = []
        save_clicked = False
        check_clicked = False
        post_clicked = False
        
        try:
            # Step 1: Hover over Fleet menu
            # Fleet menu hover
            fleet_element, fleet_sel = await query_selector_any(page, FLEET_SELECTORS)
            
            if fleet_element:
                await fleet_element.hover()
                await page.wait_for_timeout(1000)  # Wait for dropdown to appear
                navigation_steps.append(f"Fleet menu hovered via {fleet_sel}")
                logger.info(f"Hovered Fleet via selector: {fleet_sel}")
                
                # Step 2: Hover over Card Services in the dropdown
                card_services_element, cs_sel = await query_selector_any(page, CARD_SERVICES_SELECTORS)
                
                if card_services_element:
                    await card_services_element.hover()
                    await page.wait_for_timeout(1000)  # Wait for submenu to appear
                    navigation_steps.append(f"Card Services submenu hovered via {cs_sel}")
                    logger.info(f"Hovered Card Services via selector: {cs_sel}")
                    
                    # Step 3: Click on Transactions
                    transaction_element, tr_sel = await query_selector_any(page, TRANSACTION_SELECTORS)
                    
                    if transaction_element:
                        await transaction_element.click()
                        await page.wait_for_load_state("networkidle", timeout=10000)
                        navigation_steps.append(f"Transactions clicked via {tr_sel}")
                        logger.info(f"Clicked Transactions via selector: {tr_sel}")
                        
                        # Step 4: Click Import button on transactions page
                        import_button_element, import_sel, _ = await query_selector_any_in_page_or_frames(page, IMPORT_BUTTON_SELECTORS)
                        
                        if import_button_element:
                            await import_button_element.click()
                            await page.wait_for_load_state("networkidle", timeout=10000)
                            navigation_steps.append(f"Import button clicked via {import_sel}")
                            logger.info(f"Clicked Import via selector: {import_sel}")
                            
                            # Step 5: Fill input field with "CALNS"
                            ok, sel = await fill_first(page, INTERFACE_CODE_INPUT_SELECTORS, "CALNS")
                            if ok:
                                navigation_steps.append(f"Interface code filled with 'CALNS' via {sel}")
                                logger.info(f"Filled interface code with CALNS via selector: {sel}")

                                # Wait 2 seconds as requested
                                await page.wait_for_timeout(2000)
                                navigation_steps.append("Waited 2 seconds after input")
                                
                                # Step 6: Click search button and handle popup window
                                search_button_element, sb_sel, _ = await query_selector_any_in_page_or_frames(page, SEARCH_BUTTON_SELECTORS)

                                if search_button_element:
                                    navigation_steps.append(f"Search button found via {sb_sel}")
                                    logger.info(f"Found search button via selector: {sb_sel}")

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
                                        logger.debug(f"Frames after popup: {len(frames)}")

                                        dropzone_frame = None
                                        file_uploaded = False
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
                                            logger.info(f"Found dropzone in frame: {dropzone_frame.url}")

                                            # Wait for the dropzone inside that frame
                                            try:
                                                await dropzone_frame.wait_for_selector(DROPZONE_SELECTOR, timeout=20000)
                                                
                                                # Click browse and attach file if available
                                                if upload_file_local_path and os.path.exists(upload_file_local_path):
                                                    try:
                                                        # Prefer direct file input if present
                                                        file_input = await dropzone_frame.query_selector(FILE_INPUT_SELECTOR)
                                                        if file_input:
                                                            await dropzone_frame.set_input_files(FILE_INPUT_SELECTOR, upload_file_local_path)
                                                            navigation_steps.append(f"File uploaded via set_input_files: {os.path.basename(upload_file_local_path)}")
                                                            file_uploaded = True
                                                            await page.wait_for_timeout(2000)
                                                            navigation_steps.append("Waited for file upload to process")
                                                            logger.info("File uploaded via set_input_files (frame)")
                                                        else:
                                                            # Fall back to page-level file chooser while clicking inside frame
                                                            async with page.expect_file_chooser() as fc_info:
                                                                await dropzone_frame.click(f"{DROPZONE_SELECTOR} a")
                                                            file_chooser = await fc_info.value
                                                            await file_chooser.set_files(upload_file_local_path)
                                                            navigation_steps.append(f"File uploaded via file chooser: {os.path.basename(upload_file_local_path)}")
                                                            file_uploaded = True
                                                            await page.wait_for_timeout(2000)
                                                            navigation_steps.append("Waited for file upload to process")
                                                            logger.info("File uploaded via file chooser (frame)")
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
                                                        await dropzone_frame.click(f"{DROPZONE_SELECTOR} a")
                                                        navigation_steps.append("Clicked 'browse' link inside dropzone frame (no file upload)")
                                                    except Exception:
                                                        navigation_steps.append("Dropzone link not clickable without file")
                                                    
                                            except Exception as browse_error:
                                                navigation_steps.append(f"Failed to click 'browse' link inside frame: {browse_error}")

                                        else:
                                            # Fallback — maybe dropzone is in main DOM, but just delayed
                                            try:
                                                await page.wait_for_selector(DROPZONE_SELECTOR, timeout=20000)
                                                
                                                # Click browse and attach file if available (main page)
                                                if upload_file_local_path and os.path.exists(upload_file_local_path):
                                                    try:
                                                        file_input = await page.query_selector(FILE_INPUT_SELECTOR)
                                                        if not file_input:
                                                            navigation_steps.append("No file input found on main page")
                                                        else:
                                                            await page.set_input_files(FILE_INPUT_SELECTOR, upload_file_local_path)
                                                            navigation_steps.append(f"File uploaded via set_input_files on main page: {os.path.basename(upload_file_local_path)}")
                                                            logger.info("File uploaded via set_input_files (main page)")
                                                            file_uploaded = True
                                                            # Wait 2 sec for Catch-E to parse file
                                                            await page.wait_for_timeout(2000)

                                                    except Exception as upload_error:
                                                        navigation_steps.append(f"Upload error inside CALNS frame: {upload_error}")
                                                    finally:
                                                        try:
                                                            if os.path.exists(upload_file_local_path):
                                                                os.remove(upload_file_local_path)
                                                                navigation_steps.append("Temporary file cleaned up")
                                                        except:
                                                            pass
                                                else:
                                                    await page.click(f"{DROPZONE_SELECTOR} a")
                                                    navigation_steps.append("Clicked 'browse' link successfully on main page (no file upload)")
                                                    
                                            except Exception as browse_error:
                                                navigation_steps.append(f"Browse link not found after waiting: {browse_error}")
                                        
                                        # If a file was uploaded, wait 5s then click Upload
                                        if file_uploaded:
                                            try:
                                                await page.wait_for_timeout(5000)
                                                navigation_steps.append("Waited 5 seconds before clicking Upload")
                                                logger.debug("Waiting before Upload click complete")

                                                ok, sel = await click_first(page, UPLOAD_BUTTON_SELECTORS)
                                                if not ok:
                                                    navigation_steps.append("Upload button not found after file selection")
                                                    logger.error("Upload button not found")
                                                else:
                                                    # After successful click, wait briefly for any DOM updates
                                                    await page.wait_for_timeout(2000)
                                                    navigation_steps.append(f"Clicked Upload via {sel}; post-upload wait completed")
                                                    logger.info(f"Clicked Upload via selector: {sel}")

                                                    # Validation 2: record already exists -> invoice field not present
                                                    invoice_el, invoice_sel, _ = await query_selector_any_in_page_or_frames(page, INVOICE_INPUT_SELECTORS)
                                                    if not invoice_el:
                                                        navigation_steps.append("Invoice input not present; record likely exists")
                                                        logger.error("Validation failed: record_exists (invoice field missing)")
                                                        # Early return error
                                                        return {
                                                            "success": False,
                                                            "status": "error",
                                                            "error": {
                                                                "key": "record_exists",
                                                                "message": "Record already exists; invoice number input not shown"
                                                            },
                                                            "data": {
                                                                "navigation_steps": navigation_steps
                                                            }
                                                        }

                                                    # Fill the invoice number if provided
                                                    if credentials.invoice_number:
                                                        try:
                                                            await invoice_el.fill(credentials.invoice_number)
                                                            navigation_steps.append(f"Filled invoice number via {invoice_sel}")
                                                            logger.info(f"Filled invoice field via selector: {invoice_sel}")
                                                        except Exception as inv_err:
                                                            navigation_steps.append("Failed to fill invoice number even though field present")
                                                            logger.error(f"Failed to fill invoice number: {inv_err}")
                                                    else:
                                                        navigation_steps.append("No invoice_number provided in request; skipping fill")
                                                        logger.debug("No invoice number provided in payload")

                                                    # Compare displayed total_gross with provided gross; if equal, click Save
                                                    # Find total_gross text; wait briefly for it to render
                                                    displayed_gross_text = None
                                                    for _ in range(8):  # up to ~8s
                                                        displayed_gross_text = await read_text(page, TOTAL_GROSS_SELECTOR)
                                                        if displayed_gross_text and displayed_gross_text.strip():
                                                            break
                                                        await page.wait_for_timeout(1000)

                                                    provided_gross_norm = normalize_amount(credentials.gross)
                                                    displayed_gross_norm = normalize_amount(displayed_gross_text)
                                                    logger.info(f"Gross check: raw_displayed='{displayed_gross_text}', displayed_norm='{displayed_gross_norm}', provided_norm='{provided_gross_norm}'")

                                                    # Validation 1: gross must match
                                                    if not displayed_gross_norm:
                                                        logger.error("Validation failed: gross_not_found")
                                                        return {
                                                            "success": False,
                                                            "status": "error",
                                                            "error": {
                                                                "key": "gross_not_found",
                                                                "message": "Could not read total gross from the page"
                                                            },
                                                            "data": {
                                                                "navigation_steps": navigation_steps,
                                                                "raw_displayed_gross": displayed_gross_text
                                                            }
                                                        }
                                                    if not provided_gross_norm:
                                                        logger.error("Validation failed: gross_invalid (payload)")
                                                        return {
                                                            "success": False,
                                                            "status": "error",
                                                            "error": {
                                                                "key": "gross_invalid",
                                                                "message": "Provided gross is invalid or unparseable"
                                                            },
                                                            "data": {
                                                                "navigation_steps": navigation_steps,
                                                                "provided_gross": credentials.gross
                                                            }
                                                        }

                                                    if displayed_gross_norm != provided_gross_norm:
                                                        logger.error(f"Validation failed: gross_mismatch (displayed={displayed_gross_norm}, provided={provided_gross_norm})")
                                                        return {
                                                            "success": False,
                                                            "status": "error",
                                                            "error": {
                                                                "key": "gross_mismatch",
                                                                "message": f"Gross mismatch: displayed={displayed_gross_norm}, provided={provided_gross_norm}"
                                                            },
                                                            "data": {
                                                                "navigation_steps": navigation_steps
                                                            }
                                                        }

                                                    navigation_steps.append(f"total_gross matches provided gross ({displayed_gross_norm})")
                                                    logger.info("Validation passed: gross matched")

                                                    # Passed validations — attempt to click Save
                                                    ok, save_sel = await click_first(page, SAVE_BUTTON_SELECTORS)
                                                    if not ok:
                                                        navigation_steps.append("Save button not found after gross match")
                                                        logger.error("Save button not found after gross match")
                                                        save_clicked = False
                                                    else:
                                                        save_clicked = True
                                                        # Allow some time for server-side save to process
                                                        try:
                                                            await page.wait_for_load_state("networkidle", timeout=8000)
                                                        except Exception:
                                                            await page.wait_for_timeout(3000)
                                                        navigation_steps.append(f"Clicked Save via {save_sel}; post-save wait completed")
                                                        logger.info(f"Clicked Save via selector: {save_sel}")

                                                        # After Save, wait 2 seconds then click Check
                                                        await page.wait_for_timeout(2000)
                                                        navigation_steps.append("Waited 2 seconds after Save")
                                                        ok, check_sel = await click_first(page, CHECK_BUTTON_SELECTORS)
                                                        if ok:
                                                            check_clicked = True
                                                            navigation_steps.append(f"Clicked Check via {check_sel}")
                                                            logger.info(f"Clicked Check via selector: {check_sel}")
                                                            # Wait 3 seconds after Check
                                                            await page.wait_for_timeout(3000)
                                                            navigation_steps.append("Waited 3 seconds after Check")
                                                            # Additional stabilization wait
                                                            try:
                                                                await page.wait_for_load_state("networkidle", timeout=6000)
                                                            except Exception:
                                                                await page.wait_for_timeout(1500)
                                                            # Inspect error area to decide whether to post
                                                            error_text = await read_text(page, '#error_msg')
                                                            norm_err = (error_text or '').replace('\xa0', ' ').strip()
                                                            if not norm_err:
                                                                # No error shown; attempt to click Post
                                                                ok, post_sel = await click_first(page, POST_BUTTON_SELECTORS)
                                                                if ok:
                                                                    post_clicked = True
                                                                    navigation_steps.append(f"Clicked Post via {post_sel}")
                                                                    logger.info(f"Clicked Post via selector: {post_sel}")
                                                                    try:
                                                                        await page.wait_for_load_state("networkidle", timeout=8000)
                                                                    except Exception:
                                                                        await page.wait_for_timeout(2000)
                                                                else:
                                                                    # Check if Post button exists but is disabled
                                                                    post_btn_el, post_btn_sel, _ = await query_selector_any_in_page_or_frames(page, POST_BUTTON_ANY_SELECTORS)
                                                                    if post_btn_el:
                                                                        try:
                                                                            is_disabled = await post_btn_el.is_disabled()
                                                                        except:
                                                                            # Fallback: check disabled attribute
                                                                            is_disabled = await post_btn_el.get_attribute('disabled') is not None
                                                                        
                                                                        if is_disabled:
                                                                            # Post button exists and is disabled, click Abort and return error
                                                                            navigation_steps.append(f"Post button found but is disabled (via {post_btn_sel})")
                                                                            logger.error("Post button is disabled after Check, clicking Abort")
                                                                            abort_ok, abort_sel = await click_first(page, ABORT_BUTTON_SELECTORS)
                                                                            if abort_ok:
                                                                                navigation_steps.append(f"Clicked Abort via {abort_sel}")
                                                                                logger.info(f"Clicked Abort via selector: {abort_sel}")
                                                                            else:
                                                                                navigation_steps.append("Abort button not found")
                                                                                logger.error("Abort button not found")
                                                                            return {
                                                                                "success": False,
                                                                                "status": "error",
                                                                                "error": {
                                                                                    "key": "post_button_disabled",
                                                                                    "message": "Post button is disabled after Check validation"
                                                                                },
                                                                                "data": {
                                                                                    "navigation_steps": navigation_steps
                                                                                }
                                                                            }
                                                                        else:
                                                                            navigation_steps.append(f"Post button found but could not be clicked (via {post_btn_sel})")
                                                                            logger.error("Post button exists but click failed")
                                                                    else:
                                                                        navigation_steps.append("Post button not found after Check")
                                                                        logger.error("Post button not found on page")
                                                            else:
                                                                # Found error text after Check — return error
                                                                logger.error(f"Check failed with message: {norm_err}")
                                                                return {
                                                                    "success": False,
                                                                    "status": "error",
                                                                    "error": {
                                                                        "key": "check_failed",
                                                                        "message": norm_err
                                                                    },
                                                                    "data": {"navigation_steps": navigation_steps}
                                                                }
                                                        else:
                                                            navigation_steps.append("Check button not found after Save")
                                                            logger.error("Check button not found after Save")
                                            except Exception as upload_click_error:
                                                navigation_steps.append(f"Failed to click Upload button: {upload_click_error}")

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
        await browser.close()
        await playwright.stop()
        logger.info("✅ Automation completed successfully!")
        
        return {
            "success": True,
            "status": "completed",
            "message": "Login and navigation completed",
            "data": {
                "username_filled": username_filled,
                "password_filled": password_filled,
                "submit_clicked": submit_clicked,
                "navigation_success": navigation_success,
                "save_clicked": save_clicked,
                "check_clicked": check_clicked,
                "post_clicked": post_clicked,
                "navigation_steps": navigation_steps,
                "final_url": final_url,
                "page_title": page_title
            }
        }
        
    except Exception as e:
        logger.error(f"❌ Automation failed: {str(e)}")
        logger.exception("Full error traceback:")
        try:
            if browser:
                await browser.close()
                logger.info("🔄 Browser cleaned up after error")
            if playwright:
                await playwright.stop()
        except Exception:
            logger.warning("⚠️  Failed to cleanup browser/playwright")
        
        return {
            "success": False,
            "status": "error",
            "message": f"Login failed: {str(e)}",
            "error": str(e)
        }

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