import json
import os.path
import re
import time

from google.auth.transport.requests import Request
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

import bot

global checkpick
global leftcheckpick
global prevlist

prevlist = []
checkpick = []
leftcheckpick = []

def getspredsheetid():
    auth_str = os.getenv('SAMPLE_SPREADSHEET_ID')

    # Check if the environment variable is set
    if auth_str:
        # Parse the JSON string into a dictionary
        spreadid = json.loads(auth_str)

        # Print the dictionary (optional)
        return spreadid
    else:
        print("SPREAD_SHEET_ID environment variable is not set.")

def getuserrange():
    auth_str = os.getenv('SPREAD_SHEET_RANGES')

    # Check if the environment variable is set
    if auth_str:
        # Parse the JSON string into a dictionary
        auth_ranges = json.loads(auth_str)

        # Print the dictionary (optional)
        return auth_ranges
    else:
        print("SPREAD_SHEET_RANGES environment variable is not set.")

# If modifying these scopes, delete the file token.json.
#SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
SCOPES = os.getenv('SCOPES')

# The ID and range of a sample spreadsheet.
SPREADSHEET_ID_dct = getspredsheetid()
SPREADSHEET_RANGES = getuserrange()
SERVICE_ACCOUNT_FILE = r'servicefile.json'


# Used for authentication with out service account, do not recommended to use this approach. only used for testing

def get_google_sheets_token():

    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.

    creds = None
    # Check if the token already exists
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    
    # If no valid credentials are available, or the token has expired, fetch new token.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'client_secret.json', SCOPES)
            creds = flow.run_local_server(port=3000)
        # Save the credentials for the next run
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    return creds


# PICK LIST
def updatepicklist(members_list, tracker, todo, leftmem):
    global checkpick
    global leftcheckpick
    global prevlist
    
    print("in pick list")
    SPREADSHEET_ID = SPREADSHEET_ID_dct[tracker]

    creds = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE)
    
    try:
        
        service = build("sheets", "v4", credentials=creds)
        pickme = SPREADSHEET_RANGES[tracker]["pickme"]

        sheet = service.spreadsheets()
        current_values = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=f'{pickme}:{pickme}').execute()
        existing_values = current_values.get('values', [])

        if not existing_values:
            raise ValueError("No data found in the specified column.")

        # The first item is the heading, retain it separately
        
        heading = next(val for i,val in enumerate(existing_values, start=1) if val)  # Assume the first row contains the heading
        
        column_data = set(item[0] for item in existing_values[1:] if item)  # Flatten and skip the heading
        
        
        # Use sets for tracking members
        members_set = set(members_list)
        checkpick_set = set(item[0] for item in checkpick)
        leftcheckpick_set = set(item[0] for item in leftcheckpick)

        # print("this is it no? column and mmebers list", column_data, members_list)
        # print("this is the leftlist", leftcheckpick_set)
        # print("seeing the checkerpicked", checkpick_set)
        # print("number members set", members_set)
        remaining_items = [heading]  # Start with the heading as the first item in the list

        if todo:  # Add new members
            # Handle members who have left the VC and need to be checked
            
            if prevlist:
                for memberpv in prevlist:
                    member = memberpv[0]
                    if member not in checkpick_set and member not in leftcheckpick_set:
                        # Member left the VC and is not checked, mark them as checked
                        print("see who got cheked", member)
                        checkpick_set.add(member)

            for member in members_set:
                if member not in column_data and member not in checkpick_set and member not in leftcheckpick_set:
                    # Member is new, add them to the sheet
                    remaining_items.append([member])
                elif member in column_data and member in checkpick_set:
                    # Member was checked but re-added to the sheet by the overseer, uncheck them
                    checkpick_set.remove(member)
                    remaining_items.append([member])
                elif member in column_data and member not in checkpick_set and member not in leftcheckpick_set:
                    remaining_items.append([member])
                elif member in leftcheckpick_set and member not in checkpick_set:
                    leftcheckpick_set.remove(member)
                    remaining_items.append([member])

        else:  # Handle the case when removing members
            # Add current members still in the VC from the sheet list
            remaining_items += [[member] for member in column_data if member in members_set]

            # Check and process members no longer in the VC or who need to be removed
            for prev_member in prevlist:
                member_name = prev_member[0]
                if member_name not in members_set and member_name not in column_data and member_name not in checkpick_set:
                    # Member is no longer in the VC and was on the sheet, mark them as checked
                    print("this isthe cheked when left",member_name)
                    leftcheckpick_set.add(member_name)
                    checkpick_set.add(member_name)
                elif member_name in checkpick_set and member_name not in members_set and member_name not in column_data:
                    leftcheckpick_set.add(member_name)
                    continue
                    # Member is already checked, do nothing
        
                # Handle the manually removed member (leftmem) if present
            if leftmem:
                for member in leftmem:
                    if member not in column_data and member not in checkpick_set:
                        leftcheckpick_set.add(member)
                    

        # If the overseer manually added a member but they are not in the VC, uncheck and remove them
        for member in column_data:
            if member in checkpick_set and member not in members_set:
                # Member was manually added but isn't in the VC, uncheck and remove from the sheet
                checkpick_set.remove(member)
            if member not in members_set and member not in checkpick_set:
                # Remove the member if they are not in VC and not checked
                print("see it", [member])
                leftcheckpick_set.add(member)
        
        for member in members_set:
            if member not in column_data and member not in checkpick_set:
                #they are checked becaus they are in the vc but not on the list
                checkpick_set.add(member)


        print("after they leaver and added to left", leftcheckpick_set)

        #print("this is the final list", remaining_items)
        prevlist = remaining_items

        # Clear the previous column in the sheet
        clear_range = f'{pickme}:{pickme}'
        sheet.values().clear(spreadsheetId=SPREADSHEET_ID, range=clear_range).execute()
        
        # Start range to replace the join list
        SAMPLE_RANGE_NAME = getstartpos(pickme, remaining_items, existing_values)

        #Sortign the remaining items using the custom sort key
        remaining_items = [remaining_items[0]] + sorted(remaining_items[1:], key=sort_key)
        
        # Joinlist update
        sheet.values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=SAMPLE_RANGE_NAME,
            valueInputOption="USER_ENTERED",
            body={"values": remaining_items}
        ).execute()

        # Update global lists
        checkpick = [[item] for item in checkpick_set]
        leftcheckpick = [[item] for item in leftcheckpick_set]

        print("Updated Mass List successfully")

    except HttpError as err:
        print("Error occurred:", err)


def addtosheet(members_name, tracker):

    # members_name structur {name: user_joined_left_timedate}
    SPREADSHEET_ID = SPREADSHEET_ID_dct[tracker]
    
    
    #remove the previous token to generate new token because recurrent token didnt work.
    #os.remove('token.json')

    creds = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE)
    
    try:
        
        service = build("sheets", "v4", credentials=creds)
        column = SPREADSHEET_RANGES[tracker]["column"]
        joincol = SPREADSHEET_RANGES[tracker]["jointime"]

        getname =[]
        gettime =[]

        # Splitting the names and times
        for keys, values in members_name.items():
            getname.append(keys)
            gettime.append(values)

        times = [[item] for item in gettime]
        names = [[item] for item in getname]

        # Read the current content of the column to find the first empty row
        
        # Call the sheets API
        sheet = service.spreadsheets()
        current_values = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=f'{column}:{column}').execute()
        currenttime_values = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=f'{column}:{column}').execute()

        existing_values = current_values.get('values', [])
        existingtimevalues = currenttime_values.get('values', [])

        # (NAMES) Find the first empty row (row after the last filled cell)
        first_empty_row = len(existing_values) + 1  # Next empty row is after the last filled row
        SAMPLE_RANGE_NAME = f"{column}{first_empty_row}:{column}{first_empty_row+len(names)-1}"

        result = (
            sheet.values()
            .update(spreadsheetId=SPREADSHEET_ID, range=SAMPLE_RANGE_NAME, valueInputOption="USER_ENTERED",
                    body={"values": names})
            .execute()
        )


        # (TIME) Find the first empty row (row after the last filled cell for time column)
        time_first_empty_row = len(existingtimevalues) + 1  # Next empty row is after the last filled row
        SAMPLE_RANGE_TIME = f"{joincol}{time_first_empty_row}:{joincol}{time_first_empty_row+len(times)-1}"

        result = (
            sheet.values()
            .update(spreadsheetId=SPREADSHEET_ID, range=SAMPLE_RANGE_TIME, valueInputOption="USER_ENTERED",
                    body={"values": times})
            .execute()
        )


        print("updates sheet successfully")
    except HttpError as err:
        print("error happened",err)



def getstartpos(column, remaining_items, existing_values):

    SAMPLE_RANGE_NAME = None
    
    try:
        # Find the first non-empty value's index (assuming all empty cells are represented as empty strings or None)
        first_filled_row = next(i for i, val in enumerate(existing_values, start=1) if val)
    except StopIteration:
        # Handle the case where no non-empty values are found
        first_filled_row = f"{column}{1}:{column}{1+len(remaining_items)-1}"
    if first_filled_row is not None:
        SAMPLE_RANGE_NAME = f"{column}{first_filled_row}:{column}{first_filled_row+len(remaining_items)-1}"

    return SAMPLE_RANGE_NAME





def remove_and_update_items(remove_list, left_list, tracker):

    # remove_list and leftlist contruct : {name: user_joined_left_timedate}
    SPREADSHEET_ID = SPREADSHEET_ID_dct[tracker]

    creds = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE)

    try:

        service = build("sheets", "v4", credentials=creds)
        column = SPREADSHEET_RANGES[tracker]["column"]
        jointime = SPREADSHEET_RANGES[tracker]["jointime"]
        leftcol = SPREADSHEET_RANGES[tracker]["leftcol"]
        lefttime = SPREADSHEET_RANGES[tracker]["lefttime"]
        pickme = SPREADSHEET_RANGES[tracker]["pickme"]

        getjoinname =[]
        getjointime =[]
        getleftname =[]
        getlefttime =[]

        remaining_items = []

        # Splitting the names and times for removelist
        for keys, values in remove_list.items():
            getjoinname.append(keys)
            getjointime.append(values)


        # Making the remove list
        # times = [[item] for item in getjointime]
        # names = [[item] for item in getjoinname]

        # Splitting the names and times for removelist
        for keys, values in left_list.items():
            getleftname.append(keys)
            getlefttime.append(values)
        

        # Making the left list
        lefttimes = [[item] for item in getlefttime]
        leftnames = [[item] for item in getleftname]

        print(lefttimes, leftnames,"in left column")
        # Get the data from the joinlist column (JOIN LIST column)
        sheet = service.spreadsheets()
        current_values = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=f'{column}:{column}').execute()
        existing_values = current_values.get('values', [])


        # Fetch the times column values
        result = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=f'{jointime}:{jointime}').execute()
        values = result.get('values', [])
        jointimeitems = [[item[0]] for item in values if item]

        
        # Flatten the column data and remove the items in `remove_list`
        column_data = [item[0] for item in existing_values if item]  # Flattened column data
        
        # Gets the remaing members and keeps there coresponding join itmes
        for i in range(0, len(column_data)):
            
            if column_data[i] not in getjoinname:
                remaining_items.append([column_data[i]])
            else:
                del jointimeitems[i]
                
        # Update the original column with remaining items (make it continuous)
        # Find the first empty row (row after the last filled cell)

        clear_range = f'{column}:{column}'
        clear_rangetime = f'{jointime}:{jointime}'

        
        # Startig range to replace the join list
        SAMPLE_RANGE_NAME = getstartpos(column, remaining_items, existing_values)
        #clear the join list column
        sheet.values().clear(spreadsheetId=SPREADSHEET_ID, range=clear_range).execute()
        # joinlist update
        sheet.values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=SAMPLE_RANGE_NAME,
            valueInputOption="USER_ENTERED",
            body={"values": remaining_items}
        ).execute()

        # Startig range to replace the JOIN TIME LIST
        SAMPLE_RANGE_NAME = getstartpos(jointime, remaining_items, existing_values)
        #clear the join time list
        sheet.values().clear(spreadsheetId=SPREADSHEET_ID, range=clear_rangetime).execute()
        # jointimelist update
        sheet.values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=SAMPLE_RANGE_NAME,
            valueInputOption="USER_ENTERED",
            body={"values": jointimeitems}
        ).execute()


        # Finds the next possition to start adding the list of items to. (Left column)
        current_values = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=f'{leftcol}:{leftcol}').execute()
        existing_values = current_values.get('values', [])
        first_empty_row = len(existing_values) + 1  # Next empty row is after the last filled row
        SAMPLE_RANGE_NAME = f"{leftcol}{first_empty_row}:{leftcol}{first_empty_row+len(getjoinname)-1}"

        # Fill in the removed items in the column to the right
        sheet.values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=SAMPLE_RANGE_NAME,
            valueInputOption="USER_ENTERED",
            body={"values": leftnames}
        ).execute()

        current_values = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=f'{lefttime}:{lefttime}').execute()
        existing_values = current_values.get('values', [])
        first_empty_row = len(existing_values) + 1  # Next empty row is after the last filled row
        SAMPLE_RANGE_NAME = f"{lefttime}{first_empty_row}:{lefttime}{first_empty_row+len(getjointime)-1}"

        # Add the time that the member left at.
        sheet.values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=SAMPLE_RANGE_NAME,
            valueInputOption="USER_ENTERED",
            body={"values": lefttimes}
        ).execute()


        print("Updated successfully!")
    except HttpError as e:
        print(f"An error occurred: {e}")


# Clears all colums with data that was added form the traker fucntion from the sheet  starting from a speciic row

def clear_columns(username):
    print("about to clear columns")

    global checkpick
    global leftcheckpick
    global prevlist

    prevlist = []
    checkpick = []
    leftcheckpick = []

    SPREADSHEET_ID = SPREADSHEET_ID_dct[username]
    creds = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE)
    service = build("sheets", "v4", credentials=creds)
    sheet = service.spreadsheets()

    # Define column ranges to clear
    column_ranges = {
        "column": SPREADSHEET_RANGES[username]["column"],
        "jointime": SPREADSHEET_RANGES[username]["jointime"],
        "leftcol": SPREADSHEET_RANGES[username]["leftcol"],
        "lefttime": SPREADSHEET_RANGES[username]["lefttime"],
        "pickme": SPREADSHEET_RANGES[username]["pickme"]
    }

    # Generate the start row ranges for each column that have data to clear
    clear_ranges = []
    for key, column in column_ranges.items():
        start_row = firstfilled(column, sheet, SPREADSHEET_ID)
        if start_row:
            clear_ranges.append(start_row)

    # Use a single batchUpdate request to clear all specified ranges
    requests = [{"range": clear_range} for clear_range in clear_ranges]
    if requests:
        sheet.values().batchClear(spreadsheetId=SPREADSHEET_ID, body={"ranges": clear_ranges}).execute()
        print(f"Successfully cleared values in columns: {', '.join(column_ranges.keys())}")
    else:
        print("No data to clear in specified columns.")


def firstfilled(column, sheet, SPREADSHEET_ID):

    # Fetch only the first few rows (e.g., first 100 rows, adjust as needed)
    result = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=f'{column}1:{column}10').execute()
    values = result.get('values', [])

    # Find the first row with a value
    first_filled_row = 0

    for i, row in enumerate(values):
        if row and row[0].strip():  # Check if the cell has any value
            first_filled_row = i + 1
            break

    # If there's at least one filled row, clear everything after it
    if first_filled_row > 0:
        # Clear everything after the first filled row
        clear_range = f'{column}{first_filled_row + 1}:{column}'
        return clear_range
    else:
        print(f"No values found in column {column}.")
        return None


def getguild():
    guilds_auth_str = os.getenv('GUILDS_AUTH')

    # Check if the environment variable is set
    if guilds_auth_str:
        # Parse the JSON string into a dictionary
        guildnames = json.loads(guilds_auth_str)

        # Print the dictionary (optional)
        print(guildnames)
    else:
        print("GUILDS_AUTH environment variable is not set.")
    
    print(guildnames.keys())


def getauthusers():
    auth_str = os.getenv('Auth_MEMBER')

    # Check if the environment variable is set
    if auth_str:
        # Parse the JSON string into a dictionary
        auth_users = json.loads(auth_str)

        # Print the dictionary (optional)
        return auth_users
    else:
        print("Auth USERS environment variable is not set.")


# Custom sort key that prioritizes numbers, then characters, then letters
def sort_key(item):
    name = item[0]
    
    # Extract tag (if any) at the beginning of the name (e.g., [CG]), or set as an empty string
    tag_match = re.match(r'^\[\w+\]\s*', name)
    tag = tag_match.group(0) if tag_match else ''
    
    # Remove the tag from the name for further sorting
    name_without_tag = name[len(tag):].strip()
    
    # Split name into components: digits, non-alphanumeric (characters), and alphabetic parts
    components = re.findall(r'(\d+|[^\w\s]|[a-zA-Z]+)', name_without_tag)
    
    # Custom sorting logic:
    # - Numbers are sorted as integers.
    # - Characters and letters are sorted as strings (case-insensitive for letters).
    sorted_components = []
    for comp in components:
        if comp.isdigit():
            # Sort digits as integers
            sorted_components.append((0, int(comp)))
        elif re.match(r'^\W', comp):
            # Special characters come second, sort by their ASCII values
            sorted_components.append((1, comp))
        else:
            # Letters come last, sorted alphabetically (case-insensitive)
            sorted_components.append((2, comp.lower()))
    
    # Return a tuple to sort by tag first (if it exists), then by the rest of the name
    return (tag, sorted_components)


# if __name__ == "__main__":
    