import sys
sys.path.insert(0, "/Users/zainabfatima/Desktop/nexus-erp/ai-module")
from sqlalchemy import create_engine, text

engine = create_engine(
    "postgresql://nexus_user:nexus_pass@localhost:5432/nexus_erp"
)

def init_db():
    with engine.connect() as conn:
        # Drop and recreate tables cleanly
        conn.execute(text("DROP TABLE IF EXISTS notifications CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS procurement_orders CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS inventory_items CASCADE"))

        conn.execute(text("""
            CREATE TABLE inventory_items (
                item_id VARCHAR(20) PRIMARY KEY,
                name VARCHAR(100),
                category VARCHAR(30),
                unit VARCHAR(20),
                min_threshold INT,
                current_stock INT,
                daily_consumption FLOAT,
                vendor VARCHAR(100),
                vendor_email VARCHAR(100),
                critical_threshold INT,
                reorder_quantity INT,
                last_updated TIMESTAMP DEFAULT NOW()
            )
        """))

        conn.execute(text("""
            CREATE TABLE procurement_orders (
                order_id VARCHAR(20) PRIMARY KEY,
                item_id VARCHAR(20),
                item_name VARCHAR(100),
                category VARCHAR(30),
                quantity INT,
                unit VARCHAR(20),
                vendor VARCHAR(100),
                vendor_email VARCHAR(100),
                trigger_type VARCHAR(30),
                stage VARCHAR(50) DEFAULT 'Pending Verification',
                contract_status VARCHAR(20) DEFAULT 'Pending',
                email_sent BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT NOW(),
                expected_delivery DATE,
                accepted_by VARCHAR(100),
                accepted_at TIMESTAMP
            )
        """))

        conn.execute(text("""
            CREATE TABLE notifications (
                id SERIAL PRIMARY KEY,
                type VARCHAR(50),
                title VARCHAR(200),
                message TEXT,
                is_read BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT NOW(),
                order_id VARCHAR(20),
                item_name VARCHAR(100),
                category VARCHAR(30)
            )
        """))

        conn.commit()
        print("Tables created.")

        # Seed all 24 items
        conn.execute(text("""
            INSERT INTO inventory_items VALUES
            -- GENERATION
            ('GEN-001','Gas Turbine Blades','Generation','units',20,8,0.3,'Siemens Energy','gen@siemens.com',4,40),
            ('GEN-002','Generator Rotor Coils','Generation','units',15,12,0.2,'ABB Ltd','orders@abb.com',3,30),
            ('GEN-003','Diesel Fuel Stock','Generation','liters',50000,9000,800,'PSO Pakistan','orders@pso.com',10000,100000),
            ('GEN-004','Cooling Tower Fills','Generation','units',100,85,1.5,'Brentwood Industries','orders@brentwood.com',20,200),
            ('GEN-005','Steam Boiler Tubes','Generation','units',200,45,2.0,'Vallourec','orders@vallourec.com',40,400),
            ('GEN-006','Transformer Oil','Generation','liters',10000,1800,120,'Shell Pakistan','orders@shell.com',2000,20000),
            ('GEN-007','Generator Brushes','Generation','units',500,420,8.0,'Schunk Group','orders@schunk.com',100,1000),
            ('GEN-008','Fuel Filters','Generation','units',300,55,4.0,'Parker Hannifin','orders@parker.com',60,600),
            -- INFRASTRUCTURE
            ('INF-001','Distribution Transformers (11kV)','Infrastructure','units',50,142,2.5,'Siemens AG','orders@siemens.com',10,100),
            ('INF-002','Circuit Breakers (33kV)','Infrastructure','units',30,23,1.2,'ABB Ltd','orders@abb.com',6,60),
            ('INF-003','Power Cables (HT)','Infrastructure','meters',5000,8500,120,'Nexans','orders@nexans.com',1000,10000),
            ('INF-004','Transmission Towers (Steel)','Infrastructure','units',25,8,0.2,'KEC International','orders@kec.com',5,50),
            ('INF-005','Insulators (Porcelain)','Infrastructure','units',500,312,15,'NGK Insulators','orders@ngk.com',100,1000),
            ('INF-006','Surge Arresters','Infrastructure','units',100,67,3.0,'ABB Ltd','orders@abb.com',20,200),
            ('INF-007','Underground Cable Joints','Infrastructure','units',150,28,1.5,'Prysmian Group','orders@prysmian.com',30,300),
            ('INF-008','ACSR Conductors','Infrastructure','kg',2000,350,25,'Hengtong Group','orders@hengtong.com',400,4000),
            -- OPERATIONAL
            ('OPS-001','Smart Meters (AMI)','Operational','units',200,4,8.0,'Siemens AG','orders@siemens.com',40,400),
            ('OPS-002','Relay Protection Units','Operational','units',40,31,1.0,'Schneider Electric','orders@schneider.com',8,80),
            ('OPS-003','Copper Conductors','Operational','kg',1000,2,45,'Prysmian Group','orders@prysmian.com',200,2000),
            ('OPS-004','Safety Helmets','Operational','units',100,78,2.0,'3M Pakistan','orders@3m.com',20,200),
            ('OPS-005','Insulated Gloves (HV)','Operational','pairs',150,110,3.0,'Honeywell','orders@honeywell.com',30,300),
            ('OPS-006','Multimeters','Operational','units',50,42,0.5,'Fluke Corporation','orders@fluke.com',10,100),
            ('OPS-007','Cable Ties and Conduits','Operational','rolls',300,45,8.0,'HellermannTyton','orders@hellermann.com',60,600),
            ('OPS-008','Earthing Kits','Operational','units',80,14,1.0,'Eritech','orders@eritech.com',16,160)
            ON CONFLICT (item_id) DO NOTHING
        """))
        conn.commit()
        print("24 items seeded across 3 categories.")

if __name__ == "__main__":
    init_db()
