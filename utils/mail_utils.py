import smtplib


class SmtpCredentials:
    mailbox = ''
    password = ''
    smtp_server = ''
    port = 465

    def __init__(self, mailbox, password, smtp_server, port):
        self.mailbox = mailbox
        self.password = password
        self.smtp_server = smtp_server
        self.port = port


def send_email(credentials: SmtpCredentials, to, subject: str, body: str):
    """
    Function may throw an exception if mail sending has failed
    :param credentials: SmtpCredentials representing server, port and other authorization data
    :param to: list A list of addresses to send this mail to. A bare
string will be treated as a list with 1 address.
    :param subject:
    :param body:
    """
    message = 'Subject: {}\n\n{}'.format(subject, body)

    server = smtplib.SMTP_SSL(credentials.smtp_server, credentials.port)
    server.ehlo()
    server.login(credentials.mailbox, credentials.password)
    server.sendmail(credentials.mailbox, to, message)
    server.close()
