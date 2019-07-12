import json, os, logging, re
import boto3
from intuitlib.client import AuthClient
from intuitlib.enums import Scopes
from quickbooks import QuickBooks
from quickbooks.objects.vendor import Vendor 
from quickbooks.objects.account import Account
from quickbooks.objects.purchase import Purchase
from quickbooks.objects.bill import Bill
from quickbooks.objects.billpayment import BillPayment

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOGLEVEL", "INFO"))

TABLE = os.environ.get("TABLE", 'dev-plugin')
ENV = os.environ.get("STAGE", 'dev')
CLIENT_KEY = os.environ.get("CLIENT_KEY")
CLIENT_SECRET = os.environ.get("CLIENT_SECRET")
REDIRECT_URI = os.environ.get("REDIRECT_URI", 'localhost:5000')
QBO_ENV = os.environ.get("QBO_ENV", 'sandbox')

auth_client = AuthClient(
         CLIENT_KEY,
         CLIENT_SECRET,
         REDIRECT_URI,
         QBO_ENV
) 

def setup(event, context):
   payload = event['Records']
   user = payload['user']
   company = payload['company']
   client = get_qbo_client(user, company)
   account = create_lcfs_account(client)
   balance = get_balance()
   fund_account(account, balance)
   




def handler (event, context):
   data = json.loads(event['body'])
   logger.debug(json.dumps(data))
   db = boto3.resource('dynamodb')
   table = db.Table(TABLE)
   response = table.get_items(Key={'user': data['from']})
   if 'Items' not in response:
      return { 
         'statusCode': 200
      }
   else:
      auth_client = AuthClient(
         CLIENT_KEY,
         CLIENT_SECRET,
         REDIRECT_URI,
         QBO_ENV
      ) 
      client = QuickBooks(
         auth_client=auth_client,
         refresh_token=response['Item']['qbo_refresh_token'],
         environment=ENV,
         company_id=response['Item']['realm_id']
      )
      vendor = Vendor.filter(Active=True, DisplayName=data['to'], qb=client)
      if len(vendor) == 0:
         vendor = Vendor()
         vendor.DisplayName = data['to']
         vendor.save(qb=client)
         logger.debug("vendor saved")
      else: 
         vendor = vendor[0]
      account = Account.filter(Name="Left Coast Financial", qb=client)
      if len(account) == 0:
         account = setup_account(client)
      else:
         account = account[0]
      logger.debug("ACCOUNT: " + json.dumps(account[0].to_json()))
      #bill = create_bill(vendor[0], account[0], data['amount'], client)
      amount = float(data['amount'])
      #pay_bill(bill, vendor[0], account[0], amount, client)
      purchase(vendor, account, amount, client, data['description'])
   return { 'statusCode': 200 }


def purchase(vendor, account, amount, client, description=None):
   purchase = Purchase().from_json(
      {
        "PaymentType": "Check", 
        "AccountRef": {
          "value": account.Id
        }, 
        "EntityRef": {
           "type": "Vendor",
           "value": vendor.Id
        },
        "PrivateNote": description,
        "Line": [
          {
            "DetailType": "AccountBasedExpenseLineDetail", 
            "Amount": amount, 
            "AccountBasedExpenseLineDetail": {
              "AccountRef": {
                "value": account.Id
              }
            }
          }
         ]
      }
   )
   return purchase.save(qb=client)

def create_lcfs_account(client):
   account = Account.filter(Name="Left Coast Financial", qb=client)
   if len(account) == 0:
      logger.debug("Setting up LCFS account...")
      account = Account()
      account.Name = "Left Coast Financial"
      account.AccountType = "Bank"
      account.AccountSubType = "Checking"
   return account.save(qb=client)

def fund_account(account, amount, client):
   equity_account = Account.filter(
      Active=True, 
      Name="Opening Balance Equity", 
      qb=client
   )
   deposit = Deposit().from_json(
       {
          "Line": [
            {
              "DetailType": "DepositLineDetail", 
              "Amount": float(amount), 
              "DepositLineDetail": {
                "AccountRef": {
                  "value": equity_account[0].Id
                }
              }
            }
          ], 
          "DepositToAccountRef": {
            "value": account.Id
          }
        }
   )
   deposit = deposit.save(qb=client)
   return account

def create_bill(vendor, account, amount, client):
   bill = Bill()
   bill = bill.from_json(
      {
         "Line": [
            {
               "DetailType": "AccountBasedExpenseLineDetail", 
               "Id": 1,
               "Amount": float(amount), 
               "AccountBasedExpenseLineDetail": {
                  "AccountRef": {
                     "value": account.Id
                  }
               }
            }
         ], 
         "VendorRef": {
            "value": vendor.Id
         }
      }   
   )
   logger.debug("BILL: " + json.dumps(bill.to_json()))
   return bill.save(qb=client)
   

def pay_bill(bill, vendor, account, amount, client):
   payment = BillPayment()
   payment = payment.from_json(
      {
        "VendorRef": {
          "value": vendor.Id
         }, 
         "TotalAmt": amount, 
         "PayType": "Check", 
         "Line": [
            {
               "Amount": amount,
               "LinkedTxn": [
               {
                  "TxnId": bill.Id,
                  "TxnType": "Bill"
               }
               ]
            }
          ], 
         "CheckPayment": {
            "BankAccountRef": {
               "value": account.Id
             }
          }
      }
   )
   logger.debug("PAYMENT: " + json.dumps(payment.to_json()))
   return payment.save(qb=client)