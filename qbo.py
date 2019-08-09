import json, os, logging, re, time, random
import boto3
import requests
from intuitlib.client import AuthClient
from intuitlib.enums import Scopes
from quickbooks import QuickBooks
from quickbooks.objects.vendor import Vendor 
from quickbooks.objects.account import Account
from quickbooks.objects.purchase import Purchase
from quickbooks.objects.deposit import Deposit
from quickbooks.objects.bill import Bill
from quickbooks.objects.billpayment import BillPayment
from quickbooks.objects.payment import Payment
from quickbooks.objects.customer import Customer
from boto3.dynamodb.conditions import Key, Attr

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOGLEVEL", "INFO"))

TABLE = os.environ.get("TABLE", 'dev-plugin')
ENV = os.environ.get("STAGE", 'dev')
CYCLOS_URL = os.environ.get('CYCLOS_URL', 'https://dev.leftcoastfs.com/lcfs_dev')
CLIENT_KEY = os.environ.get("CLIENT_KEY")
CLIENT_SECRET = os.environ.get("CLIENT_SECRET")
REDIRECT_URI = os.environ.get("REDIRECT_URI", 'localhost:5000')
QBO_ENV = os.environ.get("QBO_ENV", 'sandbox')
PURCHASE_QUEUE = os.environ.get("PURCHASE_QUEUE", 'qbo-purchase')
PAYMENT_QUEUE = os.environ.get("PAYMENT_QUEUE", 'qbo-payment')
CYCLOS_TOKEN = os.environ.get("CYCLOS_TOKEN")

def setup(event, context):
   payload = json.loads(event['Records'][0]['body'])
   user = payload['user']
   company = payload['company']
   client = get_qbo_client(user, company)
   account = Account.filter(Name="Left Coast Financial", qb=client)
   if len(account) == 0:
      account = create_lcfs_account(client)
      cyclos_token = get_token(user, company)
      balance = get_balance(user, cyclos_token)
      fund_account(account, balance, client)
   activate(user, company)
   
def get_qbo_client(user, company):
   db = boto3.resource('dynamodb')
   table = db.Table(TABLE)
   response = table.get_item(Key={'user': user, 'company': company})
   token = response['Item']['qbo_refresh_token']
   auth_client = AuthClient(
      CLIENT_KEY,
      CLIENT_SECRET,
      REDIRECT_URI,
      QBO_ENV
   ) 
   return QuickBooks(
      auth_client=auth_client,
      refresh_token=token,
      environment=QBO_ENV,
      company_id=company
   )

#
# Lambda handler
#
def refresh_tokens(event, context):
   db = boto3.resource('dynamodb')
   table = db.Table(TABLE)
   response = table.scan()
   for item in response['Items']: 
      logger.debug('Refreshing company {}'.format(item['company']))
      token = refresh_token(item['qbo_refresh_token'])
      table.update_item(
         Key={ 
            'company': item['company'], 
            'user': item['user'] 
         },
         UpdateExpression="set #attr = :token",
         ExpressionAttributeValues={ ':token': token },
         ExpressionAttributeNames={ '#attr': 'qbo_refresh_token' }
      )
   logger.info("All tokens refreshed")

def refresh_token(token):
   auth_client = AuthClient(
      CLIENT_KEY,
      CLIENT_SECRET,
      REDIRECT_URI,
      QBO_ENV
   )
   auth_client.refresh(refresh_token=token)
   return auth_client.refresh_token

def activate(user, company):
   db = boto3.resource('dynamodb')
   table = db.Table(TABLE)
   table.update_item(
      Key={
         'user': user,
         'company': company
      },
      UpdateExpression="set #s = :r",
      ExpressionAttributeValues={
         ':r': 'ACTIVE',
      },
      ExpressionAttributeNames={
         '#s': 'status'
      }
   )

def get_balance(user, token):
   url = CYCLOS_URL+'/api/'+user+'/accounts'
   headers = {
      'Principal': 'username',
      'Authorization': 'Basic '+token,
      'Accept': 'application/json'
   }
   res = requests.get(url, headers=headers)
   if res.status_code == 200:
      data = res.json()
      balance = data[0]['status']['balance']
      return balance


def get_token(user, company):
   return CYCLOS_TOKEN

def handler (event, context):
   data = json.loads(event['body'])
   logger.debug(json.dumps(data))
   db = boto3.resource('dynamodb')
   table = db.Table(TABLE)
   sqs = boto3.resource('sqs')
   purchase_queue = sqs.get_queue_by_name(QueueName=PURCHASE_QUEUE)
   payment_queue = sqs.get_queue_by_name(QueueName=PAYMENT_QUEUE)

   response = table.query(
      KeyConditionExpression=Key('user').eq(data['fromUser'])
   )
   for item in response['Items']:
      data['company'] = item['company']
      data['user'] = item['user']
      purchase_queue.send_message(MessageBody=json.dumps(data))

   response = table.query(
      KeyConditionExpression=Key('user').eq(data['toUser'])
   )
   for item in response['Items']:
      data['company'] = item['company']
      data['user'] = item['user']
      payment_queue.send_message(MessageBody=json.dumps(data))

   return { 'statusCode': 200 }   

def create_vendor(user, company, vendorName):
   client = get_qbo_client(user, company)
   vendors = Vendor.filter(Active=True, DisplayName=vendorName, qb=client)
   if len(vendors) > 0:
      return vendor[0]
   #
   # Check for inactive vendors with the same name and rename
   #  them since we cant delete them
   logger.debug("Check for inactive vendor")
   query = "Active = False AND DisplayName LIKE '{}%'".format(vendorName)
   vendors = Vendor.where(query, qb=client)
  #vendors = Vendor.filter(DisplayName=vendorName, qb=client)
   for vendor in vendors:
      #logger.debug("Renaming inactive vendor")
      #vendor.DisplayName = vendorName + 'deleted' + str(time.time())
      logger.debug("Reactivate vendor")
      vendor.Active = True
      vendor.DisplayName = vendorName
      return vendor.save(qb=client)
   
   vendor = Vendor()
   vendor.DisplayName = vendorName
   return vendor.save(qb=client)

def create_customer(user, company, name):
   client = get_qbo_client(user, company)
   customer = Customer.filter(Active=True, DisplayName=name, qb=client)
   if len(customer) == 0:
      logger.debug("creating customer: "+name+" as "+user)
      customer = Customer()
      customer.DisplayName = name
      customer = customer.save(qb=client)
      logger.debug("customer saved")
   else: 
      customer = customer[0]
   return customer 

def do_purchase(event, context):
   data = json.loads(event['Records'][0]['body'])
   #bill = create_bill(vendor[0], account[0], data['amount'], client)
   amount = float(data['amount'])
   user = data['user']
   client = get_qbo_client(user, data['company'])
   account = Account.filter(Name='Left Coast Financial', qb=client)[0]
   vendor = create_vendor(user, data['company'], data['to'])
   #pay_bill(bill, vendor[0], account[0], amount, client)
   purchase(vendor, account, amount, client, data['description'])
   return { 'statusCode': 200 }

def do_payment(event, context):
   data = json.loads(event['Records'][0]['body'])
   amount = data['amount']
   user = data['user']
   company = data['company']
   client = get_qbo_client(user, company)
   account = Account.filter(Name='Left Coast Financial', qb=client)[0]
   customer = create_customer(user, company, data['from'])
   payment(customer, account, amount, client, data['description'])
   return { 'statusCode': 200 }

def ach(event, context):
   logger.debug(event)
   return { 'statusCode': 200 }

def payment(customer, account, amount, client, description=None):
   payment = Payment().from_json(
      {
         "PrivateNote": description,
         "TotalAmt": amount, 
         "CustomerRef": {
            "value": customer.Id
         },
         "DepositToAccountRef":  {
            "value": account.Id
         }
      }
   )
   return payment.save(qb=client)

def purchase(vendor, account, amount, client, description=None):
   purchase_acct = Account.filter(Name='Purchases', qb=client)[0]
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
                     "value": purchase_acct.Id
                  }
               } 
            }
         ]
      }
   )
   return purchase.save(qb=client)

def create_lcfs_account(client):
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
         "PrivateNote": "Initial LCFS account link",
          "Line": [
            {
              "Description": "Initial LCFS account link",
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
   logger.info("deposited "+str(amount))
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