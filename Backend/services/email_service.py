import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from utils.logger import get_logger

logger = get_logger(__name__)

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
PLATFORM_NAME = "Trading Platform"

def send_email(to_email: str, subject: str, body: str) -> bool:
    """
    Core utility to send a plain text email using Gmail SMTP.
    """
    email_user = os.getenv("EMAIL_USER")
    email_pass = os.getenv("EMAIL_PASS")
    
    if not email_user or not email_pass:
        logger.error("SMTP credentials (EMAIL_USER/EMAIL_PASS) are missing from environment.")
        return False
        
    msg = MIMEMultipart()
    msg['From'] = email_user
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))
    
    try:
        logger.info(f"Attempting to send email to {to_email} with subject '{subject}'...")
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=10)
        server.starttls()
        server.login(email_user, email_pass)
        server.send_message(msg)
        server.quit()
        logger.info(f"Email sent successfully to {to_email}")
        return True
    except Exception as e:
        # Log exception details but do not expose raw error to user
        logger.error(f"Failed to send email to {to_email}: {str(e)}")
        return False

def send_account_created_email(to_email: str, username: str, fullname: str, role: str, password: str) -> bool:
    """
    Sends the welcome/account creation email to a newly registered user.
    """
    subject = f"Welcome to {PLATFORM_NAME}"
    body = (
        f"Hello {fullname},\n\n"
        f"Your account has been created successfully.\n\n"
        f"Username: {username}\n"
        f"Role: {role}\n"
        f"Password: {password}\n\n"
        f"You can now log in to the platform.\n\n"
        f"If you require a password change, please contact your administrator.\n\n"
        f"Regards,\n"
        f"{PLATFORM_NAME}"
    )
    return send_email(to_email, subject, body)

def send_password_reset_email(to_email: str, username: str, fullname: str, role: str, password: str) -> bool:
    """
    Sends the password reset email to a user when updated by a MASTER administrator.
    """
    subject = "Your Password Has Been Reset"
    body = (
        f"Hello {fullname},\n\n"
        f"Your account password has been updated by an administrator.\n\n"
        f"Username: {username}\n"
        f"Role: {role}\n"
        f"New Password: {password}\n\n"
        f"If you were not expecting this change, please contact your administrator immediately.\n\n"
        f"Regards,\n"
        f"{PLATFORM_NAME}"
    )
    return send_email(to_email, subject, body)
