import configparser
import zipfile

import time

import dropbox
import fnmatch
import os
import plist_utils


PLIST_CONTENT_TEMPLATE = '<?xml version="1.0" encoding="UTF-8"?>\
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\
<plist version="1.0">\
<dict>\
    <key>items</key>\
    <array>\
        <dict>\
            <key>assets</key>\
            <array>\
                <dict>\
                    <key>kind</key>\
                    <string>software-package</string>\
                    <key>url</key>\
                    <string>{key_url}</string>\
                </dict>\
            </array>\
            <key>metadata</key>\
            <dict>\
                <key>bundle-identifier</key>\
                <string>{key_bundle_identifier}</string>\
                <key>bundle-version</key>\
                <string>{key_bundle_version}</string>\
                <key>kind</key>\
                <string>software</string>\
                <key>title</key>\
                <string>{key_title}</string>\
            </dict>\
        </dict>\
    </array>\
</dict>\
</plist>'


HTML_CONTENT = '<!DOCTYPE HTML>\
<html>\
    <head>\
        <title>{key_title}</title>\
        <meta charset="UTF-8">\
    </head>\
    <body>\
<h1>{key_title}</h1>\
<h2><a href="itms-services://?action=download-manifest&url={key_plist_url}">Install</a></h2>\
<h2><a href="itms-services://?action=download-manifest&url={key_plist_ios8_url}">iOS8-Install</a></h2>\
    </body>\
</html>'


def analyse_ipa(ipa_file):
    with zipfile.ZipFile(ipa_file, "r") as ipa:
        ipa_info = {}
        files = ipa.namelist()
        info_plist = fnmatch.filter(files, "Payload/*.app/Info.plist")[0]
        info_plist_bin = ipa.read(info_plist)
        try:
            info = plist_utils.read_plist_from_string(info_plist_bin)
            ipa_info = info
        except:
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

    return PLIST_CONTENT_TEMPLATE.format(key_url=ipa_url, key_bundle_identifier=bundle_identifier, key_bundle_version=bundle_version, key_title=app_name)


def generate_html_content_string_for_dropbox(html_title, plist_dropbox_url, plist_ios8_dropbox_url):
    return HTML_CONTENT.format(key_title=html_title, key_plist_url=plist_dropbox_url, key_plist_ios8_url=plist_ios8_dropbox_url)


def upload_and_share_file(dbx: dropbox.Dropbox, dropbox_path, file_or_text_content):
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


def main():

    appToken = None
    config_filename = 'deploy_config.ini'
    try:
        config = configparser.ConfigParser()
        config.read(config_filename)
        appToken = config['Dropbox authorization']['AppToken']
    except Exception:
        pass

    if appToken is None:
        print('Error parsing configuration file ' + config_filename)
        exit(1)

    ipa_local_path = input('Enter full path to AdHoc ipa file: ')

    base_filename = os.path.basename(ipa_local_path)
    base_filename, ipa_extension = os.path.splitext(base_filename)
    if not '.ipa' == ipa_extension:
        print('Extension of file is not .ipa: ', ipa_extension)
        exit(1)

    dropbox_upload_dir = input('Enter Dropbox directory for all files (for example "/AdHocs/2016-07-18"): ')

    dbx = dropbox.Dropbox(appToken)
    try:
        with open(ipa_local_path, mode='rb') as f:
            ipa_dropbox_path = os.path.join(dropbox_upload_dir, base_filename + '.ipa')
            ipa_dropbox_url = upload_and_share_file(dbx, ipa_dropbox_path, f)

            plist_dropbox_path = os.path.join(dropbox_upload_dir, base_filename + '.plist')
            plist_content = generate_plist_content_string_for_dropbox(ipa_local_path, ipa_dropbox_url)
            plist_dropbox_url = upload_and_share_file(dbx, plist_dropbox_path, plist_content)

            cur_date_string = time.strftime("%Y-%m-%d")

            plist_ios8_dropbox_path = os.path.join(dropbox_upload_dir, base_filename + '-ios8.plist')
            ios8_suffix = 'dummy-' + cur_date_string
            plist_ios8_content = generate_plist_content_string_for_dropbox(ipa_local_path, ipa_dropbox_url, ios8_suffix=ios8_suffix)
            plist_ios8_dropbox_url = upload_and_share_file(dbx, plist_ios8_dropbox_path, plist_ios8_content)

            html_dropbox_path = os.path.join(dropbox_upload_dir, base_filename + '.html')
            html_content = generate_html_content_string_for_dropbox('Pragmania-' + cur_date_string, plist_dropbox_url, plist_ios8_dropbox_url)
            html_dropbox_url = upload_and_share_file(dbx, html_dropbox_path, html_content)

            print('All files uploaded')
            print('Download url: ' + html_dropbox_url)
    except Exception as err:
        print("Failed to upload file: ", err)
        exit(1)


if __name__ == '__main__':
    main()
