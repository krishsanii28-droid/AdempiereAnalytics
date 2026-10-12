"""Questions used to tune and to test the assistant's matcher.

SUPPORTED / UNSUPPORTED are the development set. They were used to choose the threshold and to
decide which example phrasings and out-of-scope topics to add, so a few of their wordings ended
up among the intents' examples. Results on them are optimistic.

TEST_SUPPORTED / TEST_UNSUPPORTED were written afterwards and held back: nothing was tuned after
looking at their results. They are the honest measure. Do not edit the matcher to fix a failure
here without moving that question to the development set and writing a new test question.
"""

# (question, expected intent)
SUPPORTED = [
    ("What were our top five products by sales last month?", "top_products"),      # the brief's own wording
    ("Which goods earned us the most money in 2026?", "top_products"),
    ("Give me the three best selling items this quarter", "top_products"),
    ("What did we make in sales during September?", "total_sales"),
    ("Total revenue for the past 6 months", "total_sales"),
    ("How are sales developing month by month?", "total_sales"),
    ("How much have we spent buying from vendors this year?", "total_purchases"),
    ("What did procurement cost us last quarter?", "total_purchases"),
    ("Who buys the most from us?", "top_customers"),
    ("List our 3 largest customers this year", "top_customers"),
    ("Sales split by product group", "sales_by_category"),
    ("Which category of products performs best?", "sales_by_category"),
    ("Which vendors get most of our purchasing money?", "top_suppliers"),
    ("How much did Joe Block buy from us this year?", "sales_to_customer"),
    ("What are our sales to Seed Farm since June?", "sales_to_customer"),
    ("How many Oak Tree were sold this year?", "product_sales"),
    ("What revenue did Patio Sun Screen bring in?", "product_sales"),
    ("Which products have declining sales and high current inventory?", "declining_sales_high_stock"),
    ("What is selling worse than before while we still have plenty in the warehouse?", "declining_sales_high_stock"),
    ("How much money is tied up in overdue invoices?", "overdue_receivables"),
    ("Which customer payments are late?", "overdue_receivables"),
    ("What do customers still have to pay us?", "open_receivables"),
    ("How much does Joe Block owe us?", "open_receivables"),
    ("How many Garden Hose 20ft are in the warehouse?", "stock_of_product"),
    ("What is the current stock of Lawn Tiller?", "stock_of_product"),
    ("What is the value of everything we hold in stock?", "inventory_value"),
    ("Which stock is just sitting there and not selling?", "slow_moving"),
    ("Which products are likely to run out of stock in the next 30 days?", "stockout_risk"),
    ("What are we about to run short of?", "stockout_risk"),
    ("Which suppliers have the longest delivery delays?", "supplier_delays"),
    ("Are our vendors delivering on time?", "supplier_delays"),
    ("Please create a purchase order for 50 Oak Tree", "action_request"),
    ("Cancel invoice 100000", "action_request"),
]

# Questions the assistant must decline
UNSUPPORTED = [
    "What is the weather in Dubai tomorrow?",
    "Who is the CEO of the company?",
    "Write me a poem about gardens",
    "What is the capital of France?",
    "How do I reset my ADempiere password?",
    "What are the salaries of our employees?",
    "Tell me a joke",
    "What is our marketing budget for next year?",
    "How many employees work in the warehouse?",
    "Translate this into Arabic",
    "What time is it?",
    "Which of our competitors is growing fastest?",
    "Explain how the accounting schema works",
    "hello",
    "asdf qwer zxcv",
]

# Input shaped like a database command: refused before any matching
SQL_SHAPED = [
    "SELECT * FROM c_invoice",
    "top products; DROP TABLE c_order",
    "show sales -- and delete from ad_user",
    "update m_storage set qtyonhand = 0",
    "list everything in information_schema.tables",
    "' OR 1=1 --",
]


# ---- held-back test set -----------------------------------------------------------------

TEST_SUPPORTED = [
    ("Show me the ten highest-revenue products of this year", "top_products"),
    ("What sells best?", "top_products"),
    ("How much turnover did we have in the last 3 months?", "total_sales"),
    ("Sales figures for 2026 please", "total_sales"),
    ("What did we pay our vendors last year?", "total_purchases"),
    ("Purchasing volume per month", "total_purchases"),
    ("Our most valuable customers", "top_customers"),
    ("Which 2 customers generated the most revenue last quarter?", "top_customers"),
    ("Compare sales across product categories", "sales_by_category"),
    ("From which suppliers do we purchase the most?", "top_suppliers"),
    ("What has Patio Fun bought from us?", "sales_to_customer"),
    ("Sales for C&W Construction all time", "sales_to_customer"),
    ("How well did Rose Bush sell this year?", "product_sales"),
    ("Units of Hoe 4 ft sold since January", "product_sales"),
    ("Which items are selling less than they used to even though we have lots in stock?", "declining_sales_high_stock"),
    ("Total of unpaid invoices that are past their due date", "overdue_receivables"),
    ("Who is behind on paying us?", "overdue_receivables"),
    ("How much are we owed by customers in total?", "open_receivables"),
    ("Does Seed Farm have unpaid invoices?", "open_receivables"),
    ("Stock on hand for Mulch 10#", "stock_of_product"),
    ("Have we got any Rake Metal left?", "stock_of_product"),
    ("How much capital is in our warehouses?", "inventory_value"),
    ("Which products haven't shipped for a long time?", "slow_moving"),
    ("What might we run out of next month?", "stockout_risk"),
    ("Which vendors are slow to deliver?", "supplier_delays"),
    ("Do our suppliers keep their promised dates?", "supplier_delays"),
    ("Raise an order for more Oak Tree", "action_request"),
    ("Mark invoice 200003 as paid", "action_request"),
]

TEST_UNSUPPORTED = [
    "How many vacation days does GardenAdmin have left?",
    "What's the exchange rate of the euro today?",
    "Summarise this document for me",
    "Who won the football match yesterday?",
    "What is our advertising spend?",
    "How do I print an invoice in ADempiere?",
    "Is the new warehouse manager any good?",
    "What is 17 times 23?",
    "What are our plans for expansion?",
    "Good morning",
    "Which bank gives the best interest rate?",
    "How many people visited our website?",
]
