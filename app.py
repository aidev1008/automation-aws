import sys
import asyncio

# THIS MUST BE FIRST!
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import os
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

# Pydantic model for login request
class LoginRequest(BaseModel):
    username: str
    password: str
    url: Optional[str] = "https://lendly.catch-e.net.au/core/login.phpo?i=&user_login=ben.lazzaro&screen_width=1536&screen_height=960"
    s3_filename: Optional[str] = None  # Filename to fetch from S3

# Global browser instance
browser_instance = None

# S3 Configuration
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "fuel-invoices-receipt")
AWS_REGION = os.getenv("AWS_REGION", "ap-southeast-2")

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
        
        # Initialize S3 client
        s3_client = boto3.client(
            's3',
            region_name=AWS_REGION,
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY")
        )
        
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
                                        navigation_steps.append("Popup window detected and loaded")

                                        # Wait a bit to ensure the frame loads
                                        await page.wait_for_timeout(2000)  # small delay for JS onblur trigger

                                        # Try to detect if page reloaded / frame changed
                                        frames = page.frames
                                        navigation_steps.append(f"After popup close, page has {len(frames)} frames")

                                        # Look for frame that contains dropzone
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

                                            # Wait for the <a> inside that frame
                                            try:
                                                await dropzone_frame.wait_for_selector('#file-attachment-dropzone a', timeout=20000)
                                                
                                                # Download file from S3 if filename is provided
                                                local_file_path = None
                                                if credentials.s3_filename:
                                                    navigation_steps.append(f"S3 filename provided: {credentials.s3_filename}")
                                                    
                                                    # Create temporary file path
                                                    temp_dir = tempfile.gettempdir()
                                                    local_file_path = os.path.join(temp_dir, credentials.s3_filename)
                                                    navigation_steps.append(f"Temp file path: {local_file_path}")
                                                    
                                                    # Download from S3
                                                    if download_file_from_s3(credentials.s3_filename, local_file_path):
                                                        navigation_steps.append("File downloaded from S3 successfully")
                                                        
                                                        # Upload the file using Playwright's file chooser
                                                        try:
                                                            # Set up file chooser listener
                                                            async with dropzone_frame.expect_file_chooser() as fc_info:
                                                                await dropzone_frame.click('#file-attachment-dropzone a')
                                                            
                                                            file_chooser = await fc_info.value
                                                            await file_chooser.set_files(local_file_path)
                                                            navigation_steps.append(f"File uploaded successfully: {credentials.s3_filename}")
                                                            
                                                            # Wait for upload to complete
                                                            await page.wait_for_timeout(2000)
                                                            navigation_steps.append("Waited for file upload to process")
                                                            
                                                        except Exception as upload_error:
                                                            navigation_steps.append(f"File upload error: {str(upload_error)}")
                                                        finally:
                                                            # Clean up temporary file
                                                            try:
                                                                if os.path.exists(local_file_path):
                                                                    os.remove(local_file_path)
                                                                    navigation_steps.append("Temporary file cleaned up")
                                                            except:
                                                                pass
                                                    else:
                                                        navigation_steps.append("Failed to download file from S3")
                                                else:
                                                    # Just click browse without uploading
                                                    await dropzone_frame.click('#file-attachment-dropzone a')
                                                    navigation_steps.append("Clicked 'browse' link inside dropzone frame (no file upload)")
                                                    
                                            except Exception as browse_error:
                                                navigation_steps.append(f"Failed to click 'browse' link inside frame: {browse_error}")

                                        else:
                                            # Fallback — maybe dropzone is in main DOM, but just delayed
                                            try:
                                                await page.wait_for_selector('#file-attachment-dropzone a', timeout=20000)
                                                
                                                # Download file from S3 if filename is provided
                                                local_file_path = None
                                                if credentials.s3_filename:
                                                    navigation_steps.append(f"S3 filename provided (main page): {credentials.s3_filename}")
                                                    
                                                    # Create temporary file path
                                                    temp_dir = tempfile.gettempdir()
                                                    local_file_path = os.path.join(temp_dir, credentials.s3_filename)
                                                    navigation_steps.append(f"Temp file path: {local_file_path}")
                                                    
                                                    # Download from S3
                                                    if download_file_from_s3(credentials.s3_filename, local_file_path):
                                                        navigation_steps.append("File downloaded from S3 successfully (main page)")
                                                        
                                                        # Upload the file using Playwright's file chooser
                                                        try:
                                                            # Set up file chooser listener
                                                            async with page.expect_file_chooser() as fc_info:
                                                                await page.click('#file-attachment-dropzone a')
                                                            
                                                            file_chooser = await fc_info.value
                                                            await file_chooser.set_files(local_file_path)
                                                            navigation_steps.append(f"File uploaded successfully: {credentials.s3_filename}")
                                                            
                                                            # Wait for upload to complete
                                                            await page.wait_for_timeout(2000)
                                                            navigation_steps.append("Waited for file upload to process")
                                                            
                                                        except Exception as upload_error:
                                                            navigation_steps.append(f"File upload error: {str(upload_error)}")
                                                        finally:
                                                            # Clean up temporary file
                                                            try:
                                                                if os.path.exists(local_file_path):
                                                                    os.remove(local_file_path)
                                                                    navigation_steps.append("Temporary file cleaned up")
                                                            except:
                                                                pass
                                                    else:
                                                        navigation_steps.append("Failed to download file from S3")
                                                else:
                                                    # Just click browse without uploading
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
        await browser.close()
        await playwright.stop()
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