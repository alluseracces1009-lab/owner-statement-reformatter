# Owner Statement Reformatter

A free tool that turns a monthly AppFolio or Buildium owner statement / general ledger
export into two clean outputs:

- **Owner summary**: a one-page view of income, expenses, distribution and ending balance
- **Schedule E breakdown**: the same month grouped by Schedule E line, with the source
  GL accounts listed for the owner's CPA

Every result is checked against your export: opening balance + income − expenses −
distributions must equal the ending balance, and every running balance must match.
If anything doesn't tie out to the penny, no statement is produced and the app shows why.

Watch the 3-minute walkthrough: https://www.youtube.com/watch?v=8pOCphcHSV8

## How to use it

1. In AppFolio or Buildium, run the **Owner Statement** or **General Ledger** report for one
   owner and one month (cash basis), and export it as CSV or Excel.
2. Upload the file. The app finds the header row and shows which columns it used.
3. If any GL accounts are new to the tool, pick a category and Schedule E line for each.
4. Click **Generate owner statements**, then download the two CSVs.
5. Click **Save my mapping** to download your account choices as a JSON file. Load it next
   month so you don't have to map the same accounts again.

No signup is needed. You can try it first with the included sample file.

## Privacy

- Uploaded files are processed in memory for your session only. This app does not write
  them to disk, keep them in a database or send them anywhere else.
- The app is hosted on Streamlit Community Cloud, so files pass through its servers while
  they're being processed.
- You can delete tenant names, addresses and account numbers before uploading. The tool
  only needs dates, GL accounts, descriptions and amounts.
- The app counts anonymous usage events (for example "a statement was generated") so we
  know whether the tool is useful. Only the event name and time are stored: never file
  contents, amounts, names or IP addresses.

## Limits

- One owner and one month per file works best.
- Schedule E line choices are a starting point. Confirm categories with the owner's CPA.
  This tool doesn't give tax advice.

## Running it yourself

    pip install -r requirements.txt
    streamlit run app.py

Tests: `pip install pytest`, then `python -m pytest -q`.
