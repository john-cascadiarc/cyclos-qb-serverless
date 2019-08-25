import unittest
import json
import warnings as warn
import random
import string
from quickbooks.objects.account import Account
from quickbooks.objects.deposit import Deposit, DepositLine 
from qbo import *

EVENT = json.loads('{"user": "cannagrow", "company": "4620816365001694530"}')
USER = EVENT.get('user')
COMPANY = EVENT.get('company')


def randomString(stringLength=10):
    letters = string.ascii_lowercase
    return ''.join(random.choice(letters) for i in range(stringLength))

class TestAccounts(unittest.TestCase):
    def setUp(self):
        self.token = get_token(USER,COMPANY)
        self.client = get_qbo_client(USER, COMPANY)

    def testCreateAccount(self):
        '''Test Creating the LCFS Bank account'''
        name = randomString()
        account = create_lcfs_account(name, self.client)
        self.assertEqual(account.Name, name)
        self.assertEqual(account.AccountType, "Bank")
        self.assertEqual(account.AccountSubType, "Checking")
    
    def testCreateEquityAccount(self):
        name = randomString()
        account = create_equity_account(name, self.client)
        self.assertIsNotNone(account)
        self.assertEqual(account.AccountType, "Equity")

    

class TestFunding(unittest.TestCase):
    def setUp(self):
        self.client = get_qbo_client(USER, COMPANY)
        self.account_name = randomString()
        self.account = create_lcfs_account(self.account_name ,self.client)
    
    def testFundAccount(self):
        '''Test funding the account Assert Balance equal to deposit'''
        account = fund_account(self.account, 1000, self.client)
        account = Account.get(account.Id, qb=self.client)
        self.assertEqual(account.CurrentBalance, 1000)

class TestBalance(unittest.TestCase):
    def setUp(self):
        self.token = get_token(USER,COMPANY)
    def testGetBalance(self):
        balance = get_balance(USER, self.token)
        self.assertIsNotNone(balance)
        self.assertGreater(balance, 0)



    
        

if __name__ == "__main__":
    unittest.main(verbosity=3)
