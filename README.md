## iOS deployment to Dropbox

Script to upload & share AdHoc ipa file to Dropbox service.

### Requirments

- OS X 10.11
- Python 3.4
- Pip package manager
- Dropbox account

### Configuration

Clone the project go to project's dir and install Dropbox SDK via the following command:

```
pip install -r requirements.txt
```

Go to Dropbox Developer's console and open "My Apps" category: https://www.dropbox.com/developers/apps

Create a new app and generate application access token. Then in project dir create deploy_config.ini file and set up it's content like this:

```
[Dropbox authorization]
AppToken = put_your_app_token_here
```