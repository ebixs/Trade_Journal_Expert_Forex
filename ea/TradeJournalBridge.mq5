//+------------------------------------------------------------------+
//| TradeJournalBridge: sends trades to the local journal and shows  |
//| its alerts on the chart. The same file builds for MT4 and MT5.   |
//| This expert is read-only: it contains no order functions.        |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026 ebixs (EXS). All rights reserved."
#property version   "1.11"
#ifdef __MQL4__
#property strict
#endif

input string InpUrl      = "http://127.0.0.1:8765"; // Journal address
input string InpToken    = "";                      // Token from the journal settings page
input int    InpSeconds  = 5;                       // Sync interval in seconds
input int    InpDays     = 90;                      // Days of history for the first import
input bool   InpPopups   = true;                    // Show a popup for each new alert

#define BATCH        150
#define MAX_LABELS   6
#define MAX_SEEN     200
#define MFE_MAX_BARS 20160
#define PREFIX       "TJ_"
#define OFFLINE_AFTER 3   // failed syncs in a row before the chart says offline
#define CALENDAR_EVERY 300
#define CALENDAR_MAX 150

struct DealRow
  {
   string id;
   string position;
   string symbol;
   string type;
   string entry;
   double volume;
   double price;
   double sl;
   double tp;
   double profit;
   double commission;
   double swap;
   double fee;
   long   time;
   long   magic;
   string comment;
   double mfe;
   double mae;
  };

datetime g_calendarAt = 0; // last time the economic calendar reached the journal
long   g_cursor = -1;       // newest broker time the journal holds; -1 means not known yet
string g_seen[];            // alert ids already shown as a popup
int    g_failures = 0;      // failed syncs in a row

//--- text helpers ---------------------------------------------------
string JsonText(string value)
  {
   StringReplace(value, "\\", "\\\\");
   StringReplace(value, "\"", "\\\"");
   StringReplace(value, "\n", " ");
   StringReplace(value, "\r", " ");
   StringReplace(value, "\t", " ");
   return "\"" + value + "\"";
  }

string Num(const double value)
  {
   if(!MathIsValidNumber(value))
      return "0";
   return DoubleToString(value, 8);
  }

string NumOrNull(const double value)
  {
   return value == 0.0 ? "null" : Num(value);
  }

string LongText(const long value)
  {
   return IntegerToString(value);
  }

//--- account ---------------------------------------------------------
string ServerOffsetJson()
  {
#ifdef __MQL5__
   long serverTime = (long)TimeTradeServer();
#else
   // TimeCurrent stops with the market, so the offset is unreliable near the weekend.
   MqlDateTime gmt;
   TimeToStruct(TimeGMT(), gmt);
   if(gmt.day_of_week == 0 || gmt.day_of_week == 6 || (gmt.day_of_week == 5 && gmt.hour >= 20))
      return "null";
   long serverTime = (long)TimeCurrent();
#endif
   long diff = serverTime - (long)TimeGMT();
   if(diff > 14 * 3600 || diff < -14 * 3600)
      return "null";
   return LongText(diff);
  }

string AccountJson()
  {
#ifdef __MQL5__
   string platform = "MT5";
#else
   string platform = "MT4";
#endif
   return "{\"login\":" + JsonText(LongText(AccountInfoInteger(ACCOUNT_LOGIN)))
          + ",\"server\":" + JsonText(AccountInfoString(ACCOUNT_SERVER))
          + ",\"broker\":" + JsonText(AccountInfoString(ACCOUNT_COMPANY))
          + ",\"name\":" + JsonText(AccountInfoString(ACCOUNT_NAME))
          + ",\"currency\":" + JsonText(AccountInfoString(ACCOUNT_CURRENCY))
          + ",\"leverage\":" + LongText(AccountInfoInteger(ACCOUNT_LEVERAGE))
          + ",\"platform\":" + JsonText(platform)
          + ",\"balance\":" + Num(AccountInfoDouble(ACCOUNT_BALANCE))
          + ",\"equity\":" + Num(AccountInfoDouble(ACCOUNT_EQUITY))
          + ",\"gmt_offset\":" + ServerOffsetJson() + "}";
  }

string PositionJson(const string id, const string symbol, const string side, const double volume,
                    const double price, const long time, const double sl, const double tp,
                    const double profit, const double swap)
  {
   return "{\"id\":" + JsonText(id) + ",\"symbol\":" + JsonText(symbol) + ",\"side\":" + JsonText(side)
          + ",\"volume\":" + Num(volume) + ",\"price\":" + Num(price) + ",\"time\":" + LongText(time)
          + ",\"sl\":" + Num(sl) + ",\"tp\":" + Num(tp) + ",\"profit\":" + Num(profit)
          + ",\"swap\":" + Num(swap) + "}";
  }

string DealJson(const DealRow &row)
  {
   return "{\"id\":" + JsonText(row.id) + ",\"position\":" + JsonText(row.position)
          + ",\"symbol\":" + JsonText(row.symbol) + ",\"type\":" + JsonText(row.type)
          + ",\"entry\":" + JsonText(row.entry) + ",\"volume\":" + Num(row.volume)
          + ",\"price\":" + Num(row.price) + ",\"sl\":" + Num(row.sl) + ",\"tp\":" + Num(row.tp)
          + ",\"profit\":" + Num(row.profit) + ",\"commission\":" + Num(row.commission)
          + ",\"swap\":" + Num(row.swap) + ",\"fee\":" + Num(row.fee)
          + ",\"time\":" + LongText(row.time) + ",\"magic\":" + LongText(row.magic)
          + ",\"comment\":" + JsonText(row.comment) + ",\"mfe\":" + NumOrNull(row.mfe)
          + ",\"mae\":" + NumOrNull(row.mae) + "}";
  }

void ClearRow(DealRow &row)
  {
   row.sl = 0;
   row.tp = 0;
   row.profit = 0;
   row.commission = 0;
   row.swap = 0;
   row.fee = 0;
   row.magic = 0;
   row.comment = "";
   row.mfe = 0;
   row.mae = 0;
  }

//--- MetaTrader 5 ----------------------------------------------------
#ifdef __MQL5__
string PositionsJson()
  {
   string out = "";
   int total = PositionsTotal();
   for(int i = 0; i < total; i++)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      string side = PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY ? "buy" : "sell";
      string item = PositionJson(LongText(PositionGetInteger(POSITION_IDENTIFIER)),
                                 PositionGetString(POSITION_SYMBOL), side,
                                 PositionGetDouble(POSITION_VOLUME),
                                 PositionGetDouble(POSITION_PRICE_OPEN),
                                 PositionGetInteger(POSITION_TIME),
                                 PositionGetDouble(POSITION_SL), PositionGetDouble(POSITION_TP),
                                 PositionGetDouble(POSITION_PROFIT), PositionGetDouble(POSITION_SWAP));
      out += (out == "" ? "" : ",") + item;
     }
   return out;
  }

void FillExcursion(DealRow &row)
  {
   long positionId = StringToInteger(row.position);
   if(!HistorySelectByPosition(positionId))
      return;
   long opened = 0;
   int total = HistoryDealsTotal();
   for(int i = 0; i < total; i++)
     {
      ulong ticket = HistoryDealGetTicket(i);
      if(HistoryDealGetInteger(ticket, DEAL_ENTRY) == DEAL_ENTRY_IN)
        {
         opened = HistoryDealGetInteger(ticket, DEAL_TIME);
         break;
        }
     }
   if(opened == 0 || (row.time - opened) / 60 > MFE_MAX_BARS)
      return;
   double highs[], lows[];
   if(CopyHigh(row.symbol, PERIOD_M1, (datetime)opened, (datetime)row.time, highs) <= 0)
      return;
   if(CopyLow(row.symbol, PERIOD_M1, (datetime)opened, (datetime)row.time, lows) <= 0)
      return;
   double high = highs[ArrayMaximum(highs)];
   double low = lows[ArrayMinimum(lows)];
   bool wasLong = row.type == "sell"; // the closing deal is opposite to the position
   row.mfe = wasLong ? high : low;
   row.mae = wasLong ? low : high;
  }

int CollectDeals(const datetime from, DealRow &rows[])
  {
   if(!HistorySelect(from, TimeCurrent() + 86400))
      return 0;
   int total = HistoryDealsTotal();
   int count = 0;
   ArrayResize(rows, BATCH);
   for(int i = 0; i < total && count < BATCH; i++)
     {
      ulong ticket = HistoryDealGetTicket(i);
      if(ticket == 0)
         continue;
      long dealType = HistoryDealGetInteger(ticket, DEAL_TYPE);
      if(dealType != DEAL_TYPE_BUY && dealType != DEAL_TYPE_SELL && dealType != DEAL_TYPE_BALANCE)
         continue;
      DealRow row;
      ClearRow(row);
      long entry = HistoryDealGetInteger(ticket, DEAL_ENTRY);
      row.id = LongText((long)ticket);
      row.position = LongText(HistoryDealGetInteger(ticket, DEAL_POSITION_ID));
      row.symbol = HistoryDealGetString(ticket, DEAL_SYMBOL);
      row.type = dealType == DEAL_TYPE_BUY ? "buy" : (dealType == DEAL_TYPE_SELL ? "sell" : "balance");
      row.entry = entry == DEAL_ENTRY_IN ? "in" : (entry == DEAL_ENTRY_OUT ? "out"
                  : (entry == DEAL_ENTRY_INOUT ? "inout" : "outby"));
      row.volume = HistoryDealGetDouble(ticket, DEAL_VOLUME);
      row.price = HistoryDealGetDouble(ticket, DEAL_PRICE);
      row.sl = HistoryDealGetDouble(ticket, DEAL_SL);
      row.tp = HistoryDealGetDouble(ticket, DEAL_TP);
      row.profit = HistoryDealGetDouble(ticket, DEAL_PROFIT);
      row.commission = HistoryDealGetDouble(ticket, DEAL_COMMISSION);
      row.swap = HistoryDealGetDouble(ticket, DEAL_SWAP);
      row.fee = HistoryDealGetDouble(ticket, DEAL_FEE);
      row.time = HistoryDealGetInteger(ticket, DEAL_TIME);
      row.magic = HistoryDealGetInteger(ticket, DEAL_MAGIC);
      row.comment = HistoryDealGetString(ticket, DEAL_COMMENT);
      rows[count] = row;
      count++;
     }
   // Done last because it replaces the history selection used by the loop above.
   for(int i = 0; i < count; i++)
      if(rows[i].entry == "out" || rows[i].entry == "outby")
         FillExcursion(rows[i]);
   return count;
  }

string CalendarValue(const bool present, const double value)
  {
   return present ? Num(value) : "null";
  }

string CalendarRows(const string currency, const datetime from, const datetime to, int &count)
  {
   string out = "";
   MqlCalendarValue values[];
   if(CalendarValueHistory(values, from, to, NULL, currency) <= 0)
      return "";
   int total = ArraySize(values);
   for(int i = 0; i < total && count < CALENDAR_MAX; i++)
     {
      MqlCalendarEvent info;
      if(!CalendarEventById(values[i].event_id, info))
         continue;
      if(info.importance != CALENDAR_IMPORTANCE_HIGH && info.importance != CALENDAR_IMPORTANCE_MODERATE)
         continue;
      string impact = info.importance == CALENDAR_IMPORTANCE_HIGH ? "high" : "medium";
      out += (out == "" ? "" : ",") + "{\"id\":" + JsonText(LongText((long)values[i].id))
             + ",\"time\":" + LongText((long)values[i].time) + ",\"currency\":" + JsonText(currency)
             + ",\"title\":" + JsonText(info.name) + ",\"code\":" + JsonText(info.event_code)
             + ",\"impact\":" + JsonText(impact)
             + ",\"forecast\":" + CalendarValue(values[i].HasForecastValue(), values[i].GetForecastValue())
             + ",\"previous\":" + CalendarValue(values[i].HasPreviousValue(), values[i].GetPreviousValue())
             + ",\"actual\":" + CalendarValue(values[i].HasActualValue(), values[i].GetActualValue()) + "}";
      count++;
     }
   return out;
  }

string CalendarJson()
  {
   datetime now = TimeTradeServer();
   if(now - g_calendarAt < CALENDAR_EVERY)
      return "";
   string currencies[3] = {"USD", "EUR", "GBP"};
   string out = "";
   int count = 0;
   for(int i = 0; i < 3; i++)
     {
      string part = CalendarRows(currencies[i], now - 2 * 86400, now + 7 * 86400, count);
      if(part != "")
         out += (out == "" ? "" : ",") + part;
     }
   return out;
  }
#endif

//--- MetaTrader 4 ----------------------------------------------------
#ifdef __MQL4__
string PositionsJson()
  {
   string out = "";
   int total = OrdersTotal();
   for(int i = 0; i < total; i++)
     {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES) || OrderType() > OP_SELL)
         continue;
      string side = OrderType() == OP_BUY ? "buy" : "sell";
      string item = PositionJson(LongText(OrderTicket()), OrderSymbol(), side, OrderLots(),
                                 OrderOpenPrice(), (long)OrderOpenTime(), OrderStopLoss(),
                                 OrderTakeProfit(), OrderProfit(), OrderSwap());
      out += (out == "" ? "" : ",") + item;
     }
   return out;
  }

void FillExcursion(DealRow &row, const datetime opened, const datetime closed)
  {
   int first = iBarShift(row.symbol, PERIOD_M1, opened, false);
   int last = iBarShift(row.symbol, PERIOD_M1, closed, false);
   int bars = first - last + 1;
   if(first < 0 || last < 0 || bars <= 0 || bars > MFE_MAX_BARS)
      return;
   int highest = iHighest(row.symbol, PERIOD_M1, MODE_HIGH, bars, last);
   int lowest = iLowest(row.symbol, PERIOD_M1, MODE_LOW, bars, last);
   if(highest < 0 || lowest < 0)
      return;
   double high = iHigh(row.symbol, PERIOD_M1, highest);
   double low = iLow(row.symbol, PERIOD_M1, lowest);
   bool wasLong = row.type == "sell"; // the closing row is opposite to the order
   row.mfe = wasLong ? high : low;
   row.mae = wasLong ? low : high;
  }

int CollectDeals(const datetime from, DealRow &rows[])
  {
   int total = OrdersHistoryTotal();
   int tickets[];
   long times[];
   int found = 0;
   ArrayResize(tickets, total);
   ArrayResize(times, total);
   for(int i = 0; i < total; i++)
     {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_HISTORY))
         continue;
      int orderType = OrderType();
      if((orderType != OP_BUY && orderType != OP_SELL && orderType != 6) || OrderCloseTime() < from)
         continue;
      // Insertion sort: MT4 does not promise that history is in time order.
      int slot = found;
      long closeTime = (long)OrderCloseTime();
      while(slot > 0 && times[slot - 1] > closeTime)
        {
         times[slot] = times[slot - 1];
         tickets[slot] = tickets[slot - 1];
         slot--;
        }
      times[slot] = closeTime;
      tickets[slot] = OrderTicket();
      found++;
     }
   int count = 0;
   ArrayResize(rows, BATCH * 2);
   for(int i = 0; i < found && i < BATCH; i++)
     {
      if(!OrderSelect(tickets[i], SELECT_BY_TICKET, MODE_HISTORY))
         continue;
      string ticket = LongText(tickets[i]);
      DealRow row;
      ClearRow(row);
      row.position = ticket;
      row.symbol = OrderSymbol();
      row.comment = OrderComment();
      row.magic = OrderMagicNumber();
      if(OrderType() == 6)
        {
         row.id = ticket + "-bal";
         row.type = "balance";
         row.entry = "in";
         row.volume = 0;
         row.price = 0;
         row.profit = OrderProfit();
         row.time = (long)OrderCloseTime();
         rows[count] = row;
         count++;
         continue;
        }
      bool isBuy = OrderType() == OP_BUY;
      row.id = ticket + "-in";
      row.type = isBuy ? "buy" : "sell";
      row.entry = "in";
      row.volume = OrderLots();
      row.price = OrderOpenPrice();
      row.time = (long)OrderOpenTime();
      rows[count] = row;
      count++;
      row.id = ticket + "-out";
      row.type = isBuy ? "sell" : "buy";
      row.entry = "out";
      row.price = OrderClosePrice();
      row.sl = OrderStopLoss();
      row.tp = OrderTakeProfit();
      row.profit = OrderProfit();
      row.commission = OrderCommission();
      row.swap = OrderSwap();
      row.time = (long)OrderCloseTime();
      FillExcursion(row, OrderOpenTime(), OrderCloseTime());
      rows[count] = row;
      count++;
     }
   return count;
  }
#endif

#ifdef __MQL4__
string CalendarJson()
  {
   return ""; // MT4 has no economic calendar; the journal uses the weekly feed instead
  }
#endif

//--- journal connection ----------------------------------------------
string DealsJson()
  {
   if(g_cursor < 0)
      return ""; // the first message only asks where the journal stopped
   datetime oldest = TimeCurrent() - InpDays * 86400;
   datetime from = g_cursor > 0 ? (datetime)(g_cursor - 60) : oldest;
   DealRow rows[];
   int count = CollectDeals(from, rows);
   string out = "";
   for(int i = 0; i < count; i++)
      out += (i == 0 ? "" : ",") + DealJson(rows[i]);
   return out;
  }

bool Post(const string body, string &reply)
  {
   char data[], result[];
   string responseHeaders;
   int size = StringToCharArray(body, data, 0, WHOLE_ARRAY, CP_UTF8);
   if(size > 0)
      ArrayResize(data, size - 1); // drop the terminating zero
   string headers = "Content-Type: application/json\r\nX-Journal-Token: " + InpToken + "\r\n";
   ResetLastError();
   int status = WebRequest("POST", InpUrl + "/api/ea/sync", headers, 8000, data, result, responseHeaders);
   if(status != 200)
     {
      g_failures++;
      if(g_failures == OFFLINE_AFTER)
         Print("Journal sync failed. HTTP ", status, ", error ", GetLastError(),
               ". Check that the journal is running, the token is right, and ", InpUrl,
               " is in Tools > Options > Expert Advisors > Allow WebRequest.");
      return false;
     }
   g_failures = 0;
   reply = CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8);
   return true;
  }

//--- chart output ----------------------------------------------------
void ShowLine(const int index, const string text, const color ink)
  {
   string name = PREFIX + IntegerToString(index);
   if(ObjectFind(0, name) < 0)
     {
      ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0);
      ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_LOWER);
      ObjectSetInteger(0, name, OBJPROP_XDISTANCE, 12);
      ObjectSetInteger(0, name, OBJPROP_YDISTANCE, 40 + index * 20);
      ObjectSetInteger(0, name, OBJPROP_FONTSIZE, 10);
      ObjectSetString(0, name, OBJPROP_FONT, "Segoe UI");
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
     }
   ObjectSetString(0, name, OBJPROP_TEXT, text);
   ObjectSetInteger(0, name, OBJPROP_COLOR, ink);
  }

void HideLinesFrom(const int index)
  {
   for(int i = index; i <= MAX_LABELS; i++)
      ObjectDelete(0, PREFIX + IntegerToString(i));
  }

bool AlreadySeen(const string id)
  {
   for(int i = ArraySize(g_seen) - 1; i >= 0; i--)
      if(g_seen[i] == id)
         return true;
   return false;
  }

void Remember(const string id)
  {
   int size = ArraySize(g_seen);
   if(size >= MAX_SEEN)
     {
      for(int i = 1; i < size; i++)
         g_seen[i - 1] = g_seen[i];
      size--;
     }
   ArrayResize(g_seen, size + 1);
   g_seen[size] = id;
  }

void ApplyReply(const string reply)
  {
   string lines[];
   int total = StringSplit(reply, '\n', lines);
   int shown = 1;
   for(int i = 0; i < total; i++)
     {
      string parts[];
      int fields = StringSplit(lines[i], '|', parts);
      if(fields == 2 && parts[0] == "CURSOR")
         g_cursor = StringToInteger(parts[1]);
      if(fields == 4 && parts[0] == "ALERT")
        {
         if(shown <= MAX_LABELS)
           {
            ShowLine(shown, parts[3], parts[2] == "stop" ? clrTomato : clrGold);
            shown++;
           }
         if(!AlreadySeen(parts[1]))
           {
            Remember(parts[1]);
            if(InpPopups)
               Alert("Journal: ", parts[3]);
           }
        }
     }
   HideLinesFrom(shown);
  }

void SyncOnce()
  {
   if(AccountInfoInteger(ACCOUNT_LOGIN) == 0)
      return;
   string calendar = CalendarJson();
   string body = "{\"account\":" + AccountJson() + ",\"positions\":[" + PositionsJson()
                 + "],\"deals\":[" + DealsJson() + "],\"calendar\":[" + calendar + "]}";
   string reply = "";
   if(Post(body, reply))
     {
      if(calendar != "")
         g_calendarAt = TimeCurrent();
      ShowLine(0, "Journal connected", clrSilver);
      ApplyReply(reply);
     }
   else
      if(g_failures >= OFFLINE_AFTER)
        {
         ShowLine(0, "Journal offline", clrTomato);
         HideLinesFrom(1);
        }
   ChartRedraw(0);
  }

//--- events ----------------------------------------------------------
int OnInit()
  {
   if(InpToken == "")
     {
      Alert("Journal: paste the token from the journal settings page into the expert inputs.");
      return INIT_PARAMETERS_INCORRECT;
     }
   EventSetTimer(InpSeconds < 2 ? 2 : InpSeconds);
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
   HideLinesFrom(0);
   ChartRedraw(0);
  }

void OnTimer()
  {
   SyncOnce();
  }

void OnTick()
  {
  }
