
##Adding a service account to authenticate automatically without user input. 

How to Use Service Accounts for Google Sheets API
Here are the steps to set up a service account and use it to access Google Sheets without user interaction:

Step 1: Create a Service Account
Go to the Google Cloud Console:

Navigate to the Google Cloud Console.
Create a New Project (if you don't have one):

Click on the project dropdown in the top navigation and select "New Project."
Enable Google Sheets API:

Go to APIs & Services > Library.
Search for Google Sheets API and enable it.
Create a Service Account:

Go to APIs & Services > Credentials.
Click on Create Credentials and select Service Account.
Fill out the service account details and click Create.
Grant Permissions (optional):

If your service account needs access to specific resources, you can grant it permissions here.
Create a Key:

After creating the service account, click on it to open the details.
Go to the Keys tab and click Add Key > Create New Key.
Choose the JSON key type and click Create. This will download a JSON file containing your service account credentials.
Step 2: Share Your Google Sheet with the Service Account
Open the Google Sheet you want the service account to access.
Click on the Share button.
Share the sheet with the service account's email address (it will look something like your-service-account-name@your-project-id.iam.gserviceaccount.com).
Make sure to give it sufficient permissions (Viewer, Editor, etc.).