import configparser
import fnmatch
import getopt
import os
import sys
import time
import zipfile

import dropbox

from utils import plist_utils
from utils.mail_utils import *

HELP_MESSAGE = 'Usage: main.py -i <input_file> -o <output_dropbox_dir> -s <optional-subject-for-mail>'
HELP_MESSAGE_FULL = 'Usage: main.py -i <input_file> -o <output_dropbox_dir> -s <optional-subject-for-mail>\n\
    Example: main.py -i /Users/user/AdHocFile.ipa -o /AdHocs/TestAdHoc -s Hello'

PLIST_CONTENT_TEMPLATE = '<?xml version="1.0" encoding="UTF-8"?>\n\
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n\
<plist version="1.0">\n\
<dict>\n\
    <key>items</key>\n\
    <array>\n\
        <dict>\n\
            <key>assets</key>\n\
            <array>\n\
                <dict>\n\
                    <key>kind</key>\n\
                    <string>software-package</string>\n\
                    <key>url</key>\n\
                    <string>{key_url}</string>\n\
                </dict>\n\
            </array>\n\
            <key>metadata</key>\n\
            <dict>\n\
                <key>bundle-identifier</key>\n\
                <string>{key_bundle_identifier}</string>\n\
                <key>bundle-version</key>\n\
                <string>{key_bundle_version}</string>\n\
                <key>kind</key>\n\
                <string>software</string>\n\
                <key>title</key>\n\
                <string>{key_title}</string>\n\
            </dict>\n\
        </dict>\n\
    </array>\n\
</dict>\n\
</plist>'

DOWNLOAD_LINK_TEMPLATE_IOS = "itms-services://?action=download-manifest&url={key_plist_url}"

DOWNLOAD_LINK_TEMPLATE_IOS_8 = "itms-services://?action=download-manifest&url={key_plist_ios8_url}"


def analyse_ipa(ipa_file):
    with zipfile.ZipFile(ipa_file, "r") as ipa:
        ipa_info = {}
        files = ipa.namelist()
        info_plist = fnmatch.filter(files, "Payload/*.app/Info.plist")[0]
        info_plist_bin = ipa.read(info_plist)
        try:
            info = plist_utils.read_plist_from_string(info_plist_bin)
            ipa_info = info
        except Exception:
            pass
        ipa.close()
        return ipa_info


def generate_plist_content_string_for_dropbox(ipa_file_path, ipa_url, ios8_suffix=None):
    ipa_info = analyse_ipa(ipa_file_path)
    if ipa_info is None:
        return None

    app_name = (
        ipa_info["CFBundleDisplayName"]
        if "CFBundleDisplayName" in ipa_info
        else ipa_info["CFBundleName"]
    )
    bundle_version = ipa_info["CFBundleVersion"]
    bundle_identifier = ipa_info["CFBundleIdentifier"]

    return PLIST_CONTENT_TEMPLATE.format(key_url=ipa_url, key_bundle_identifier=bundle_identifier,
                                         key_bundle_version=bundle_version, key_title=app_name).encode('utf-8')


def upload_and_share_file(dbx, dropbox_path, file_or_text_content):
    print('Uploading file to dropbox location: ' + dropbox_path)
    dbx.files_upload(file_or_text_content, dropbox_path)
    print('File uploaded')

    print('Building shared link... ')
    shared_url = dbx.sharing_create_shared_link_with_settings(dropbox_path)
    from urllib.parse import urlparse
    parsed_url = urlparse(shared_url.url)
    parsed_url = parsed_url._replace(netloc='dl.dropboxusercontent.com')
    parsed_url = parsed_url._replace(query=None)
    from urllib.parse import urlunparse

    shared_url_str = urlunparse(parsed_url)
    print('File shared. Download link: ' + shared_url_str)

    return shared_url_str


def upload_ipa_and_plist_files(dropbox_token, ipa_local_path, output_dropbox_dir) -> (str, str):
    """
    Create plist files from given ipa file and both ipa and plist files to Dropbox.
    Function returns tuple with 2 links: first for iOS 9-11 ipa, second for iOS 8 ipa.
    :param dropbox_token: token to authorize on Dropbox service
    :param ipa_local_path:
    :param output_dropbox_dir:
    """
    base_filename = os.path.basename(ipa_local_path)
    base_filename, ipa_extension = os.path.splitext(base_filename)
    if not '.ipa' == ipa_extension:
        print('Extension of file is not .ipa: ', ipa_extension)
        exit(1)

    dbx = dropbox.Dropbox(dropbox_token)
    try:
        with open(ipa_local_path, mode='rb') as f:
            ipa_dropbox_path = os.path.join(output_dropbox_dir, base_filename + '.ipa')
            ipa_dropbox_url = upload_and_share_file(dbx, ipa_dropbox_path, f)

            plist_dropbox_path = os.path.join(output_dropbox_dir, base_filename + '.plist')
            plist_content = generate_plist_content_string_for_dropbox(ipa_local_path, ipa_dropbox_url)
            plist_dropbox_url = upload_and_share_file(dbx, plist_dropbox_path, plist_content)

            cur_date_string = time.strftime("%Y-%m-%d")

            plist_ios8_dropbox_path = os.path.join(output_dropbox_dir, base_filename + '-ios8.plist')
            ios8_suffix = 'dummy-' + cur_date_string
            plist_ios8_content = generate_plist_content_string_for_dropbox(ipa_local_path, ipa_dropbox_url,
                                                                           ios8_suffix=ios8_suffix)
            plist_ios8_dropbox_url = upload_and_share_file(dbx, plist_ios8_dropbox_path, plist_ios8_content)

            download_link_ios = DOWNLOAD_LINK_TEMPLATE_IOS.format(key_plist_url=plist_dropbox_url)
            download_link_ios8 = DOWNLOAD_LINK_TEMPLATE_IOS_8.format(key_plist_ios8_url=plist_ios8_dropbox_url)

            return (download_link_ios, download_link_ios8)
    except Exception as err:
        print("Failed to upload file: ", err)
        exit(1)


def main():
    global opts
    config_filename = 'deploy_config.ini'
    dropbox_token = None
    mailbox = None
    password = None
    smtp_server = None
    to_whom = None
    mail_subject = None

    try:
        config = configparser.ConfigParser()
        config.read(config_filename)

        dropbox_token = config['Dropbox authorization']['AppToken']

        mailbox = config['Mail service']['Mailbox']
        smtp_server = config['Mail service']['SmtpServer']
        password = config['Mail service']['Password']

        to_whom = config['Mail service']['ToWhom']
        if to_whom is not None:
            to_whom = to_whom.split(",")
    except Exception:
        pass

    if dropbox_token is None:
        print('Error parsing configuration file: no AppToken detected ' + config_filename)
        print('No AppToken detected')
        exit(1)

    if mailbox is None or smtp_server is None or password is None:
        print('Error parsing configuration file: ' + config_filename)
        print('Not all credential info detected')
        exit(1)

    credentials = SmtpCredentials(mailbox, password, smtp_server, 465)

    try:
        opts, args = getopt.getopt(sys.argv[1:], "hi:o:s:")
    except getopt.GetoptError:
        print(HELP_MESSAGE)
        exit(1)

    ipa_local_path = None
    output_dropbox_dir = None
    for opt, arg in opts:
        if opt == '-h':
            print(HELP_MESSAGE_FULL)
            exit(1)

        if opt == "-i":
            ipa_local_path = arg
            continue

        if opt == "-o":
            output_dropbox_dir = arg

        if opt == "-s":
            mail_subject = arg

    if ipa_local_path is None or output_dropbox_dir is None:
        print(HELP_MESSAGE)
        exit(1)

    ipa_links = None
    try:
        print("Uploading files to Dropbox...")
        ipa_links = upload_ipa_and_plist_files(dropbox_token, ipa_local_path, output_dropbox_dir)
        print("Files uploaded to Dropbox:")
        print("iOS 9-11 download link: " + ipa_links[0])
        print("iOS 8 download link: " + ipa_links[1])
    except Exception as ex:
        print("Failed to upload file: ", ex)
        exit(1)

    if to_whom is None:
        print("No \"ToWhom\" field found in config file. Mail wil not be sent")
        exit(0)

    try:

        print("Sending mail...")

        mail_body = "iOS 9-11 download link: " + ipa_links[0] + "\n\niOS 8 download link: " + ipa_links[1]

        subject = mail_subject
        if subject is None:
            subject = "IPA file"

        send_email(credentials, to_whom, subject, mail_body)
        print("Mail successfully sent")
    except Exception as ex:
        print("Failed to send mail: " + str(ex))


if __name__ == '__main__':
    main()
