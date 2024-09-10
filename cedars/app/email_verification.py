"""
This page contatins the functions to allow users to authenticate themselves via an email OTP.
"""

from random import randint
from flask_mail import Message
from . import EMAIL_CONNECTOR

def send_otp_mail(otp, recipient_email):
    '''
    Sends an otp email to a recipient to verify a new mail.

    Args :
        - otp (int) : OTP to send to the email address.
        - recipient_email (str) : Email to send the OTP to.
    Returns :
        - None
    '''
    msg = Message(
        subject="CEDARS OTP",
        recipients=[recipient_email],
    )

    msg.body = "Below is the OTP to verify this email for your CEDARS account."
    msg.html = f"<b> {otp} </b>"

    EMAIL_CONNECTOR.send(msg)

def send_mail_acknowledgement(recipient_email, username, project_name):
    '''
    Sends the user an email to inform them that the email has been registered for a CEDARS project.

    Args :
        - recipient_email (str) : Email to send the OTP to.
        - username (str) : Username given during the registration of this email account.
        - project_name (str) : Name of the CEDARS project the user's email has been registered for.
    Returns :
        - None
    '''
    msg = Message(
        subject="CEDARS OTP",
        recipients=[recipient_email],
    )

    if project_name is not None:
        msg.html = f"""<p> Congratulations,
        this email has been registered for a CEDARS project : {project_name}.
        <br>
        Your username for this account is {username}. </p>"""
    else:
        msg.html = f"""<p> Congratulations, this email has been registered for a new CEDARS project.
        <br>
        Your username for this account is {username}. </p>"""

    EMAIL_CONNECTOR.send(msg)

def generate_otp(num_digits = 6):
    '''
    Generates a random numeric OTP for email verification.

    Args :
        - num_digits (int) = The number of digits for the OTP
    Returns :
        - int : Randomly generated OTP
    '''
    otp = randint(1, 9)

    for _ in range(num_digits):
        otp = (10 * otp) + randint(0, 9)

    return otp
