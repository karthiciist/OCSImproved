import json
import math
import requests
from fyers_api import accessToken, fyersModel
from flask import Flask, render_template, request, redirect, send_file, url_for
from flask import Flask
from flask import request
import webbrowser
import yfinance as yf
from ta.trend import ADXIndicator
import datetime
import pandas as pd
import time
import numpy as np
import yfinance as yf
# from stockstats import StockDataFrame
import pyodbc
import http.client
import configparser


app = Flask(__name__)

redirect_url = "http://127.0.0.1:8095/process_authcode_from_fyers"
response_t = "code"
state = "sample_state"

config_obj = configparser.ConfigParser()
config_obj.read(".\configfile.ini")
dbparam = config_obj["mssql"]
symbolparam = config_obj["symbol"]

server = dbparam["Server"]
db = dbparam["db"]


# To get client_id and client_secret from user and pass to fyers api
@app.route("/getauthcode", methods=['POST'])
def getauthcode():
    global client_id
    client_id = request.form.get('client_id')
    global client_secret
    client_secret = request.form.get('client_secret')
    session = accessToken.SessionModel(
        client_id=client_id,
        secret_key=client_secret,
        redirect_uri=redirect_url,
        response_type=response_t
    )

    response = session.generate_authcode()
    webbrowser.open(response)
    return response


# Fyres api will call back this methid with auth code. This method will use that auth code to generate access token
@app.route("/process_authcode_from_fyers")
def process_authcode_from_fyers():
    try:
        authcode = request.args.get('auth_code')
        session = accessToken.SessionModel(
            client_id=client_id,
            secret_key=client_secret,
            redirect_uri=redirect_url,
            response_type=response_t,
            grant_type="authorization_code"
        )
        session.set_token(authcode)
        response = session.generate_token()
        global access_token
        access_token = response["access_token"]
        print("access token ", access_token)
        global refresh_token
        refresh_token = response["refresh_token"]
        return render_template('authorized.html')
    except Exception as e:
        return {"status": "Failed", "data": str(e)}


@app.route("/run_ocs_strategy", methods=['POST'])
def run_ocs_strategy():
    while (True):
        try:
            time.sleep(60)
            to_log_db_dict = {}
            to_buy_db_dict = {}

            to_log_db_dict["symbol"] = symbolparam["indexsymbol"]

            # Check if it is trade time
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            to_log_db_dict["timestamp"] = now

            if is_it_trade_time():
                print("Its trade time")
                to_log_db_dict["is_trade_time"] = "Y"

                # Read DB tables and get necessary values
                conn = pyodbc.connect('Driver={SQL Server Native Client 11.0};'
                                      r'Server=' + server + ';'
                                      'Database=' + db + ';'
                                      'Trusted_Connection=yes;')  # integrated security

                cur = conn.cursor()
                cur.execute('''Select Top 1 * From [OCSTrade].[dbo].[NIFTY_1m_Ticker] Order By datetime Desc''')
                index_ticker_blob = cur.fetchall()

                index_open = float(index_ticker_blob[0][0])
                index_close = float(index_ticker_blob[0][1])
                index_high = float(index_ticker_blob[0][2])
                index_low = float(index_ticker_blob[0][3])
                index_sma = float(index_ticker_blob[0][10])
                index_smma = float(index_ticker_blob[0][11])
                index_adx = float(index_ticker_blob[0][12])
                # index_adx = 20
                index_ema9 = float(index_ticker_blob[0][13])

                to_log_db_dict["index_open"] = index_open
                to_log_db_dict["index_close"] = index_close
                to_log_db_dict["index_high"] = index_high
                to_log_db_dict["index_low"] = index_low
                to_log_db_dict["index_sma"] = index_sma
                to_log_db_dict["index_smma"] = index_smma
                to_log_db_dict["index_adx"] = index_adx
                to_log_db_dict["index_ema9"] = index_ema9


                if index_close > index_ema9:
                    # Taking call path
                    print("index_close > index_ema9")
                    print("Taking call path")
                    cur2 = conn.cursor()
                    cur2.execute('''Select Top 1 * From [OCSTrade].[dbo].[CE_STRIKE_1m_Ticker] Order By datetime Desc''')
                    strike_ticker_blob = cur2.fetchall()

                    strike_open = float(strike_ticker_blob[0][0])
                    strike_close = float(strike_ticker_blob[0][1])
                    strike_high = float(strike_ticker_blob[0][2])
                    strike_low = float(strike_ticker_blob[0][3])
                    strike_sma = float(strike_ticker_blob[0][10])
                    strike_smma = float(strike_ticker_blob[0][11])
                    strike_adx = float(strike_ticker_blob[0][12])
                    strike_ema9 = float(strike_ticker_blob[0][13])

                    epoch = int(strike_ticker_blob[0][8])
                    date_time = str(strike_ticker_blob[0][9])

                    strike_buy = strike_ticker_blob[0][17]


                    to_log_db_dict["strike_open"] = strike_open
                    to_log_db_dict["strike_close"] = strike_close
                    to_log_db_dict["strike_high"] = strike_high
                    to_log_db_dict["strike_low"] = strike_low
                    to_log_db_dict["strike_sma"] = strike_sma
                    to_log_db_dict["strike_smma"] = strike_smma
                    to_log_db_dict["strike_adx"] = strike_adx
                    to_log_db_dict["strike_ema9"] = strike_ema9

                    if strike_smma > strike_sma:
                        print("strike_smma > strike_sma")
                        hammer_formed_dict = is_hammer_formed("CE_STRIKE_1m_Ticker")

                        hammer_formed = hammer_formed_dict["hammer_formed"]
                        hammer_high = hammer_formed_dict["hammer_high"]
                        hammer_low = hammer_formed_dict["hammer_low"]

                        if hammer_formed == "Y":
                            print("hammer formed")
                            to_log_db_dict["hammer"] = "Y"

                            telegram_msg_hammer = "Hammer candle formed for " + symbolparam["cesymbol"] + " at " + str(date_time) + "%0A Open price - " + str(strike_open) + "%0A Close price - " + str(strike_close) + "%0A High price - " + str(strike_high) + "%0A Low price - " + str(strike_low) + "%0A SMA - " + str(strike_sma) + "%0A SMMA - " + str(strike_smma)
                            telegram_hammer_response = send_to_telegram(telegram_msg_hammer)
                            print("telegram_hammer_response - ", telegram_hammer_response)

                            if index_adx > 19.7:
                                print("index_adx > 19.7")
                                # if strike_buy == "Y":
                                print("strike_buy == Y")
                                to_log_db_dict["buy"] = "Y"

                                to_buy_db_dict["symbol"] = symbolparam["cesymbol"]
                                to_buy_db_dict["hammer_high"] = hammer_high
                                to_buy_db_dict["hammer_low"] = hammer_low
                                to_buy_db_dict["epoch"] = epoch
                                to_buy_db_dict["timestamp"] = now

                                # populate_buy_table(to_buy_db_dict)
                                # populate_log_table(to_log_db_dict)

                                # telegram_msg = "Buy signal for " + symbolparam["cesymbol"] + " generated"
                                # telegram_response = send_to_telegram(telegram_msg)

                                update_buy_column(epoch, "CE_STRIKE_1m_Ticker")

                                # update_buy_table(symbolparam["cesymbol"], hammer_high, hammer_low, epoch, now)
                                update_buy_table(to_buy_db_dict)

                                # print("telegram_response - ", telegram_response)
                                print("Buy signal generated")
                                print("--------------------------------------")

                            else:
                                print("ADX less than 19.7")
                                update_reason_column(epoch, "ADX < 19.7", "[OCSTrade].[dbo].[CE_STRIKE_1m_Ticker]")
                                print("--------------------------------------")
                        else:
                            to_log_db_dict["hammer"] = "N"
                            print("No hammer formed")
                            update_reason_column(epoch, "No hammer formed", "[OCSTrade].[dbo].[CE_STRIKE_1m_Ticker]")
                    else:
                        print("SMA > SMMA")
                        update_reason_column(epoch, "SMA > SMMA", "[OCSTrade].[dbo].[CE_STRIKE_1m_Ticker]")

                else:
                    # Taking put path
                    print("index_close < index_ema9")
                    print("Taking put path")
                    cur2 = conn.cursor()
                    cur2.execute(
                        '''Select Top 1 * From [OCSTrade].[dbo].[PE_STRIKE_1m_Ticker] Order By datetime Desc''')
                    strike_ticker_blob = cur2.fetchall()

                    strike_open = float(strike_ticker_blob[0][0])
                    strike_close = float(strike_ticker_blob[0][1])
                    strike_high = float(strike_ticker_blob[0][2])
                    strike_low = float(strike_ticker_blob[0][3])
                    strike_sma = float(strike_ticker_blob[0][10])
                    strike_smma = float(strike_ticker_blob[0][11])
                    strike_adx = float(strike_ticker_blob[0][12])
                    # strike_ema9 = float(strike_ticker_blob[0][13])
                    #
                    # strike_ema9 = float(strike_ticker_blob[0][13])
                    # strike_ema9 = float(strike_ticker_blob[0][13])
                    strike_ema9 = float(strike_ticker_blob[0][13])

                    epoch = int(strike_ticker_blob[0][8])
                    date_time = str(strike_ticker_blob[0][9])

                    strike_buy = strike_ticker_blob[0][17]

                    to_log_db_dict["strike_open"] = strike_open
                    to_log_db_dict["strike_close"] = strike_close
                    to_log_db_dict["strike_high"] = strike_high
                    to_log_db_dict["strike_low"] = strike_low
                    to_log_db_dict["strike_sma"] = strike_sma
                    to_log_db_dict["strike_smma"] = strike_smma
                    to_log_db_dict["strike_adx"] = strike_adx
                    to_log_db_dict["strike_ema9"] = strike_ema9

                    if strike_smma > strike_sma:
                        print("strike_smma > strike_sma")
                        hammer_formed_dict = is_hammer_formed("PE_STRIKE_1m_Ticker")

                        hammer_formed = hammer_formed_dict["hammer_formed"]
                        hammer_high = hammer_formed_dict["hammer_high"]
                        hammer_low = hammer_formed_dict["hammer_low"]

                        if hammer_formed == "Y":
                            print("hammer formed")
                            to_log_db_dict["hammer"] = "Y"

                            telegram_msg_hammer = "Hammer candle formed for " + symbolparam["pesymbol"] + " at " + str(date_time) + "%0A Open price - " + str(strike_open) + "%0A Close price - " + str(strike_close) + "%0A High price - " + str(strike_high) + "%0A Low price - " + str(strike_low) + "%0A SMA - " + str(strike_sma) + "%0A SMMA - " + str(strike_smma)
                            telegram_hammer_response = send_to_telegram(telegram_msg_hammer)
                            print("telegram_hammer_response - ", telegram_hammer_response)

                            if index_adx > 19.7:
                                print("index_adx > 19.7")
                                # if strike_buy == "Y":
                                print("strike_buy == Y")
                                to_log_db_dict["buy"] = "Y"

                                to_buy_db_dict["symbol"] = symbolparam["pesymbol"]
                                to_buy_db_dict["hammer_high"] = hammer_high
                                to_buy_db_dict["hammer_low"] = hammer_low
                                to_buy_db_dict["epoch"] = epoch
                                to_buy_db_dict["timestamp"] = now

                                # populate_buy_table(to_buy_db_dict)
                                # populate_log_table(to_log_db_dict)

                                # telegram_msg = "Buy signal for " + symbolparam["pesymbol"] + " generated"
                                # telegram_response = send_to_telegram(telegram_msg)

                                update_buy_column(epoch, "PE_STRIKE_1m_Ticker")

                                # update_buy_table(symbolparam["pesymbol"], hammer_high, hammer_low, epoch, now)
                                update_buy_table(to_buy_db_dict)

                                # print("telegram_response - ", telegram_response)
                                print("Buy signal generated")
                                print("--------------------------------------")

                            else:
                                print("ADX less than 19.7")
                                update_reason_column(epoch, "ADX < 19.7", "[OCSTrade].[dbo].[PE_STRIKE_1m_Ticker]")
                        else:
                            to_log_db_dict["hammer"] = "N"
                            print("No hammer formed")
                            update_reason_column(epoch, "No hammer formed", "[OCSTrade].[dbo].[PE_STRIKE_1m_Ticker]")
                    else:
                        print("SMA > SMMA")
                        update_reason_column(epoch, "SMA > SMMA", "[OCSTrade].[dbo].[PE_STRIKE_1m_Ticker]")
            else:
                print("not a trade time")
                to_log_db_dict["is_trade_time"] = "N"

            populate_log_table(to_log_db_dict)

        except Exception as e:
            print(e)
            continue


def is_hammer_formed(table):
    # conn = pyodbc.connect('Driver={SQL Server Native Client 11.0};'
    #                       r'Server=' + server + ';'
    #                       'Database=' + db + ';'
    #                       'Trusted_Connection=yes;')  # integrated security
    #
    # cur = conn.cursor()
    # cur.execute("Select Top 3 [hammer] From [OCSTrade].[dbo].[" + table + "] Order By datetime Desc")
    # hammers_db_result = cur.fetchall()
    #
    # for row in hammers_db_result:
    #     print(row)
    #     row_to_list = [elem for elem in row]
    #
    # try:
    #     index = row_to_list.index("Y")
    #     print("Hammer formed")
    #     return "Y"
    #
    # except ValueError:
    #     print("No hammer formed")
    #     return "N"

    conn = pyodbc.connect('Driver={SQL Server Native Client 11.0};'
                        r'Server=' + server + ';'
                        'Database=' + db + ';'
                        'Trusted_Connection=yes;')  # integrated security

    cur = conn.cursor()
    cur.execute(
        "Select Top 1 [hammer], [high], [low] From [OCSTrade].[dbo].[" + table + "] Order By datetime Desc")
    hammers_db_result = cur.fetchall()

    list_of_lists_hammers = []

    hammer_spec_dict = {}

    for row in hammers_db_result:
        print(row)
        list_of_lists_hammers.append(row)
        row_to_list = [elem for elem in row]

    for list in list_of_lists_hammers:
        hammer_formed = list[0]
        if hammer_formed == "Y":
            hammer_high = list[1]
            hammer_low = list[2]
            hammer_spec_dict["hammer_formed"] = "Y"
            hammer_spec_dict["hammer_high"] = hammer_high
            hammer_spec_dict["hammer_low"] = hammer_low
            # print("hammer formed")
            return hammer_spec_dict
        else:
            hammer_high = ""
            hammer_low = ""
            hammer_spec_dict["hammer_formed"] = "N"
            hammer_spec_dict["hammer_high"] = hammer_high
            hammer_spec_dict["hammer_low"] = hammer_low
            print("no hammer formed")

    # hammer_spec_dict = {"hammer_formed":"Y", "hammer_high":"2.5", "hammer_low":"1.5"}

    return hammer_spec_dict


def populate_buy_table(to_buy_db_dict):
    table = dbparam["buy_table"]

    symbol = to_buy_db_dict["symbol"]
    hammer_high = to_buy_db_dict["hammer_high"]
    hammer_low = to_buy_db_dict["hammer_low"]
    timestamp = to_buy_db_dict["timestamp"]

    target = ""
    buy_price = str(float(hammer_high) + 3)
    stoploss = str(float(hammer_low) - 2)

    conn = pyodbc.connect('Driver={SQL Server Native Client 11.0};'
                          r'Server=' + server + ';'
                          'Database=' + db + ';'
                          'Trusted_Connection=yes;')  # integrated security

    cursor = conn.cursor()

    SQLCommand = (
            "INSERT INTO " + table + " (symbol, buying_price, target, stoploss, hammer_high, hammer_low, timestamp) VALUES (?,?,?,?,?,?,?);")
    Values = [symbol, buy_price, target, stoploss, hammer_high, hammer_low, timestamp]
    # print(SQLCommand)
    # Processing Query
    cursor.execute(SQLCommand, Values)

    conn.commit()
    print("Buy table successfully populated")
    conn.close()


def populate_log_table(to_log_db_dict):
    table = dbparam["ocs_log_table"]
    symbol = symbolparam["indexsymbol"]

    timestamp = to_log_db_dict.get('timestamp')
    is_trade_time = to_log_db_dict.get('is_trade_time')
    index_open = to_log_db_dict.get('index_open')
    index_close = to_log_db_dict.get('index_close')
    index_high = to_log_db_dict.get('index_high')
    index_low = to_log_db_dict.get('index_low')
    index_sma = to_log_db_dict.get('index_sma')
    index_smma = to_log_db_dict.get('index_smma')
    index_adx = to_log_db_dict.get('index_adx')
    index_ema9 = to_log_db_dict.get('index_ema9')
    strike_open = to_log_db_dict.get('strike_open')
    strike_close = to_log_db_dict.get('strike_close')
    strike_high = to_log_db_dict.get('strike_high')
    strike_low = to_log_db_dict.get('strike_low')
    strike_sma = to_log_db_dict.get('strike_sma')
    strike_smma = to_log_db_dict.get('strike_smma')
    strike_adx = to_log_db_dict.get('strike_adx')
    strike_ema9 = to_log_db_dict.get('strike_ema9')
    hammer = to_log_db_dict.get('hammer')
    buy = to_log_db_dict.get('buy')

    conn = pyodbc.connect('Driver={SQL Server Native Client 11.0};'
                          r'Server=' + server + ';'
                          'Database=' + db + ';'
                          'Trusted_Connection=yes;')  # integrated security

    cursor = conn.cursor()

    SQLCommand = (
            "INSERT INTO " + table + " (symbol, timestamp, is_trade_time, index_open, index_close, index_high, index_low, index_sma, index_smma, index_adx, index_ema9, strike_open, strike_close, strike_high, strike_low, strike_sma, strike_smma, strike_adx, strike_ema9, hammer, buy) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?);")
    Values = [str(symbol), str(timestamp), str(is_trade_time), str(index_open), str(index_close), str(index_high), str(index_low),
              str(index_sma), str(index_smma), str(index_adx), str(index_ema9), str(strike_open), str(strike_close),
              str(strike_high), str(strike_low), str(strike_sma), str(strike_smma), str(strike_adx), str(strike_ema9), str(hammer), str(buy)]
    # print(SQLCommand)
    # Processing Query
    cursor.execute(SQLCommand, Values)

    conn.commit()
    print("Log table successfully populated")
    conn.close()


def is_it_trade_time():
    start_first_time_window = datetime.time(7, 15, 0)
    end_first_time_window = datetime.time(10, 45, 0)
    current_first_time_window = datetime.datetime.now().time()
    first_time_window = time_in_range(start_first_time_window, end_first_time_window, current_first_time_window)
    if first_time_window == False:
        start_second_time_window = datetime.time(10, 45, 0)
        end_second_time_window = datetime.time(16, 00, 0)
        current_second_time_window = datetime.datetime.now().time()
        second_time_window = time_in_range(start_second_time_window, end_second_time_window, current_second_time_window)

    if first_time_window:
#         print ("Time is morning trade time")
        return True
    elif second_time_window:
#         print ("Time is noon trade time")
        return True
    else:
#         print ("Not a trade time")
        return False


def time_in_range(start, end, current):
    """Returns whether current is in the range [start, end]"""
    return start <= current <= end


def send_to_telegram(text):
    try:
        conn = http.client.HTTPSConnection("api.telegram.org")
        payload = ''
        headers = {}
        text = text.replace(" ", "%20")
        conn.request("POST", "/bot6386426510:AAHfwLLcNx9yOyqw2IKFxNFqJht4PCT49XA/sendMessage?chat_id=-876428015&text=" + text, payload, headers)
        res = conn.getresponse()
        data = res.read()
        # print(data.decode("utf-8"))
        return "Y"
    except Exception as e:
        print(e)
        return "N"


def update_buy_column(epoch, table):
    conn = pyodbc.connect('Driver={SQL Server Native Client 11.0};'
                          r'Server=' + server + ';'
                          'Database=' + db + ';'
                          'Trusted_Connection=yes;')  # integrated security

    cur = conn.cursor()
    print ("update " + table + " SET buy = 'Y' where epoch = '" + str(int(epoch)) + "'")
    cur.execute("update " + table + " SET buy = 'Y' where epoch = '" + str(int(epoch)) + "'")
    conn.commit()
    print("buy update - Y")
    conn.close()


def update_buy_table(to_buy_db_dict):
    symbol = to_buy_db_dict["symbol"]
    hammer_high = to_buy_db_dict["hammer_high"]
    hammer_low = to_buy_db_dict["hammer_low"]
    epoch = to_buy_db_dict["epoch"]
    timestamp = to_buy_db_dict["timestamp"]

    conn = pyodbc.connect('Driver={SQL Server Native Client 11.0};'
                          r'Server=' + server + ';'
                          'Database=' + db + ';'
                          'Trusted_Connection=yes;')  # integrated security
    cur = conn.cursor()


    buying_price = float(hammer_high) + 2
    stoploss = float(hammer_low) - 1

    SQLCommand = (
            "INSERT INTO [OCSTrade].[dbo].[OCS_Buy] (symbol, buying_price, stoploss, hammer_high, hammer_low, timestamp, epoch) VALUES (?,?,?,?,?,?,?);")
    Values = [symbol, buying_price, stoploss, hammer_high, hammer_low, timestamp, epoch]

    cur.execute(SQLCommand, Values)

    conn.commit()
    print("Buy table successfully populated")
    conn.close()


def update_reason_column(epoch, reason, table):
    conn = pyodbc.connect('Driver={SQL Server Native Client 11.0};'
                          r'Server=' + server + ';'
                          'Database=' + db + ';'
                          'Trusted_Connection=yes;')  # integrated security

    cur = conn.cursor()
    print("update " + table + " SET reason = '" + reason + "' where epoch = '" + str(int(epoch)) + "'")
    cur.execute("update " + table + " SET reason = '" + reason + "' where epoch = '" + str(int(epoch)) + "'")
    conn.commit()
    print("reason updated")
    conn.close()




# @cross_origin("*")
@app.route('/gui')
def gui():
    return render_template('index.html')


@app.route('/showdb')
def showdb():


    table = dbparam["ocs_log_table"]

    conn = pyodbc.connect('Driver={SQL Server Native Client 11.0};'
                          r'Server=' + server + ';'
                          'Database=' + db + ';'
                          'Trusted_Connection=yes;')  # integrated security

    cursor = conn.cursor()
    SQLCommand = "SELECT * from " + table
    cursor.execute(SQLCommand)
    results = cursor.fetchall()
    # print(results)

    p = []
    # df = pd.DataFrame(results, columns=['symbol', 'timestamp', 'is_trade_time', 'close_20_sma', 'close_7_smma', 'close_9_ema', 'current_price', 'current_ema9_price', 'call_or_put', 'strike_price', 'smma_greater_than_sma', 'hammer_formed', 'adx_value', 'adx_value'])

    tbl = "<tr><td>symbol</td><td>timestamp</td><td>is_trade_time</td><td>close_20_sma</td><td>close_7_smma</td><td>close_9_ema</td><td>current_price</td><td>current_ema9_price</td><td>call_or_put</td><td>strike_price</td><td>smma_greater_than_sma</td><td>hammer_formed</td><td>adx_value</td><td>buy_signal</td></tr>"
    p.append(tbl)

    for row in results:
        a = "<tr><td>%s</td>" % row[0]
        p.append(a)
        b = "<td>%s</td>" % row[1]
        p.append(b)
        c = "<td>%s</td>" % row[2]
        p.append(c)
        d = "<td>%s</td>" % row[3]
        p.append(d)
        e = "<td>%s</td>" % row[4]
        p.append(e)
        f = "<td>%s</td>" % row[5]
        p.append(f)
        g = "<td>%s</td>" % row[6]
        p.append(g)
        h = "<td>%s</td>" % row[7]
        p.append(h)
        i = "<td>%s</td>" % row[8]
        p.append(i)
        j = "<td>%s</td>" % row[9]
        p.append(j)
        k = "<td>%s</td>" % row[10]
        p.append(k)
        l = "<td>%s</td>" % row[11]
        p.append(l)
        m = "<td>%s</td>" % row[12]
        p.append(m)
        n = "<td>%s</td></tr>" % row[13]
        p.append(n)

    contents = '''<!DOCTYPE html PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN">
    <html>
    <head>
    <meta content="text/html; charset=ISO-8859-1"
    http-equiv="content-type">
    <title>Python Webbrowser</title>
    </head>
    <body>
    <table>
    %s
    </table>
    </body>
    </html>
    ''' % (p)

    filename = 'webbrowser.html'

    def main(contents, filename):
        output = open(filename, "w")
        output.write(contents)
        output.close()

    main(contents, filename)
    webbrowser.open(filename)

    return "Please check the other tab opened for DB view"
    # return render_template('showdb.html')


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8095, debug=False)