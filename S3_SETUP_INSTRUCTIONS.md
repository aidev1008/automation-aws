# S3 Integration Setup Instructions

## Overview
The application now automatically fetches files from your S3 bucket (`fuel-invoices-receipt`) and uploads them to the Catch-e site when clicking the browse button.

## Setup Steps

### 1. Install Dependencies
Install the new boto3 dependency:
```powershell
pip install -r requirements.txt
```

### 2. Configure AWS Credentials
Create a `.env` file in the project root (copy from `.env.example`):
```env
# AWS S3 Configuration
AWS_ACCESS_KEY_ID=your_access_key_here
AWS_SECRET_ACCESS_KEY=your_secret_key_here
AWS_REGION=ap-southeast-2
S3_BUCKET_NAME=fuel-invoices-receipt
```

Replace `your_access_key_here` and `your_secret_key_here` with your actual AWS credentials.

### 3. Update Your JSON Request
Add the `s3_filename` field to your JSON request:
```json
{
    "username": "ben.lazzaro",
    "password": "your_password",
    "url": "https://lendly.catch-e.net.au/core/login.phpo?i=&user_login=ben.lazzaro&screen_width=1536&screen_height=960",
    "s3_filename": "NS_0200597867_597867_20251112033036.txt"
}
```

## How It Works

1. **File Matching**: The application reads the `s3_filename` from your JSON request
2. **S3 Download**: Automatically downloads the file from the `fuel-invoices-receipt` bucket
3. **Temporary Storage**: Saves the file temporarily to your system's temp directory
4. **Upload**: Uses Playwright's file chooser to upload the file when clicking browse
5. **Cleanup**: Removes the temporary file after upload

## Example API Call

```bash
curl -X POST "http://localhost:8000/login" \
     -H "Content-Type: application/json" \
     -d '{
       "username": "ben.lazzaro",
       "password": "your_password",
       "s3_filename": "NS_0200597867_597867_20251112033036.txt"
     }'
```

## Workflow

The automation will:
1. ✅ Login to Catch-e site
2. ✅ Navigate: Fleet → Card Services → Transactions
3. ✅ Click Import button
4. ✅ Fill "CALNS" in the interface code field
5. ✅ Click search button
6. ✅ Handle the popup window
7. ✅ **Download file from S3** (e.g., `NS_0200597867_597867_20251112033036.txt`)
8. ✅ **Automatically upload file** when browse button is clicked
9. ✅ Clean up temporary files

## Troubleshooting

### File Not Found in S3
- Verify the filename matches exactly (case-sensitive)
- Check the S3 bucket name is correct
- Ensure AWS credentials have read permissions

### AWS Credentials Error
- Verify `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` are set in `.env`
- Ensure the IAM user has `s3:GetObject` permission for the bucket
- Check the region is correct (`ap-southeast-2`)

### File Upload Fails
- Check the logs for specific error messages
- Verify the browse button selector is correct
- Ensure the file is downloaded successfully before upload

## Logs
Check `logs/automation_[date].log` for detailed execution logs including:
- S3 download status
- File upload progress
- Any errors encountered

## Security Notes
- Never commit your `.env` file to git
- Keep your AWS credentials secure
- Use IAM roles with minimal required permissions
- Consider using temporary credentials or IAM roles for EC2/Lambda
