PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS customers(
  customer_id TEXT PRIMARY KEY CHECK (customer_id GLOB 'C[0-9][0-9][0-9][0-9]'),
  full_name TEXT NOT NULL, tier TEXT NOT NULL CHECK (tier IN ('STANDARD','GOLD','PLATINUM')),
  city TEXT, joined_year INTEGER);
CREATE TABLE IF NOT EXISTS products(
  sku TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL,
  price REAL NOT NULL CHECK (price > 0), warranty_months INTEGER NOT NULL CHECK (warranty_months >= 0));
CREATE TABLE IF NOT EXISTS orders(
  order_id TEXT PRIMARY KEY CHECK (order_id GLOB 'O-[0-9][0-9][0-9][0-9][0-9][0-9]'),
  customer_id TEXT NOT NULL REFERENCES customers(customer_id),
  order_date TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('PLACED','SHIPPED','DELIVERED','CANCELLED')),
  payment_method TEXT CHECK (payment_method IN ('UPI','CARD','COD')),
  delivery_note TEXT);
CREATE TABLE IF NOT EXISTS order_items(
  order_id TEXT NOT NULL REFERENCES orders(order_id), sku TEXT NOT NULL REFERENCES products(sku),
  qty INTEGER NOT NULL CHECK (qty >= 1),
  net_unit_price REAL NOT NULL CHECK (net_unit_price > 0),
  delivered_on TEXT,
  PRIMARY KEY (order_id, sku));
CREATE TABLE IF NOT EXISTS returns(
  return_id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES orders(order_id),
  sku TEXT NOT NULL REFERENCES products(sku), requested_on TEXT,
  reason TEXT CHECK (reason IN ('DEFECTIVE','DAMAGED','WRONG_ITEM','CHANGED_MIND')),
  status TEXT CHECK (status IN ('REQUESTED','PICKED_UP','REFUNDED','REJECTED')),
  refund_amount REAL);
CREATE TABLE IF NOT EXISTS documents(
  doc_id TEXT PRIMARY KEY, title TEXT NOT NULL, issuer TEXT,
  authority_level INTEGER NOT NULL CHECK (authority_level BETWEEN 1 AND 5),
  doc_type TEXT, version TEXT NOT NULL, effective_from TEXT NOT NULL, effective_to TEXT,
  supersedes TEXT DEFAULT '', scope_categories TEXT DEFAULT 'ALL', scope_tiers TEXT DEFAULT 'ALL',
  provenance TEXT, retrieved_on TEXT, synthetic TEXT DEFAULT 'N',
  chunks_indexed INTEGER DEFAULT 0, ingested_at TEXT);
CREATE TABLE IF NOT EXISTS rule_registry(
  rule_id TEXT PRIMARY KEY, description TEXT, parameter TEXT NOT NULL, operator TEXT, value TEXT NOT NULL,
  scope_categories TEXT DEFAULT 'ALL', scope_tiers TEXT DEFAULT 'ALL',
  effective_from TEXT NOT NULL, effective_to TEXT,
  source_doc_id TEXT NOT NULL REFERENCES documents(doc_id), source_section TEXT,
  auto_extracted INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS audit_log(
  trace_id TEXT PRIMARY KEY, customer_id TEXT, ts TEXT NOT NULL, record_json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_orders_customer ON orders(customer_id);
CREATE INDEX IF NOT EXISTS ix_rules_param ON rule_registry(parameter);
