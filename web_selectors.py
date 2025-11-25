# Centralized selector definitions (renamed to avoid stdlib 'selectors' conflict)

# Login form
USERNAME_SELECTORS = [
    "input[name='username']",
    "input[name='user']",
    "input[name='email']",
    "input[name='login']",
    "input[type='text']",
    "#username",
    "#user",
    "#email",
]

PASSWORD_SELECTORS = [
    "input[name='password']",
    "input[type='password']",
    "#password",
]

SUBMIT_SELECTORS = [
    "button[type='submit']",
    "input[type='submit']",
    "button:has-text('Login')",
    "button:has-text('Sign in')",
    "input[value*='Login']",
]

# Top navigation
FLEET_SELECTORS = [
    'td[id="HM_Menu1_top"]',
    'td:has-text("Fleet")',
    '[onmouseover*="HM_Menu1"]',
    '.top_menu_off:has-text("Fleet")',
]

CARD_SERVICES_SELECTORS = [
    'text="Card Services"',
    'td:has-text("Card Services")',
    '[onmouseover]:has-text("Card Services")',
]

TRANSACTION_SELECTORS = [
    'text="Transactions"',
    'td:has-text("Transactions")',
    'a:has-text("Transactions")',
]

# Import flow
IMPORT_BUTTON_SELECTORS = [
    'input[name="button_import"]',
    'input[id="button_import"]',
    'input[value="Import"]',
    '.formbutton[value="Import"]',
]

INTERFACE_CODE_INPUT_SELECTORS = [
    'input[name="fm_int_interface_code"]',
    'input[id="fm_int_interface_code"]',
    '.forminput.border_input[name="fm_int_interface_code"]',
]

SEARCH_BUTTON_SELECTORS = [
    'i.catch_e_icon_search',
    'i.catch-e-icon-lookingglass1',
    'i[title="Find"]',
    '.catch_e_icon_search',
    '.catch-e-icon-lookingglass1',
    'i[class*="catch_e_icon_search"]',
    'i[class*="lookingglass"]',
]

# Upload controls
DROPZONE_SELECTOR = '#file-attachment-dropzone'
FILE_INPUT_SELECTOR = 'input[type="file"]'

UPLOAD_BUTTON_SELECTORS = [
    '#button_upload',
    'input#button_upload',
    'input[name="button_upload"]',
    'input.formbutton[value="Upload"]',
    'input[value="Upload"]',
]

# Invoice
INVOICE_INPUT_SELECTORS = [
    'input#invoice_no',
    'input[name="invoice_no"]',
    'input.forminput#invoice_no',
]

# Totals and save
TOTAL_GROSS_SELECTOR = '#total_gross'
SAVE_BUTTON_SELECTORS = [
    '#button_save_preview',
    'input#button_save_preview',
    'input[name="button_save_preview"]',
    'input.formbutton#button_save_preview',
    'input.formbutton[value="Save"]',
]

# Check action
CHECK_BUTTON_SELECTORS = [
    '#button_pre_check',
    'input#button_pre_check',
    'input[name="button_pre_check"]',
    'input.formbutton#button_pre_check',
    'input[value="Check"]',
    '#button_check',
    'input#button_check',
    'input[name="button_check"]',
]

# Post action (prefer enabled-only selectors)
POST_BUTTON_SELECTORS = [
    '#button_post:not([disabled])',
    'input#button_post:not([disabled])',
    'input[name="button_post"]:not([disabled])',
    'input.formbutton#button_post:not([disabled])',
    'input[value=" Post "]:not([disabled])',
    '#button_post',
    'input#button_post',
    'input[name="button_post"]',
]

# Abort action (pre-check abort button)
ABORT_BUTTON_SELECTORS = [
    '#button_pre_abort',
    'input#button_pre_abort',
    'input[name="button_pre_abort"]',
    'input.formbutton#button_pre_abort',
    'input[name="button_pre_abort"][value="Abort"]',
    'input[type="button"][name="button_pre_abort"]',
]