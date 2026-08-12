import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score
import joblib
import os

import sqlite3

def load_and_preprocess_data(db_path):
    print(f"Connecting to database at {db_path}...")
    conn = sqlite3.connect(db_path)
    
    print("Fetching data from 'sales' table...")
    # Read the data using a SQL query
    df = pd.read_sql_query('SELECT * FROM sales', conn)
    conn.close()
    
    print("Preprocessing data...")
    # Convert dates
    df['Date'] = pd.to_datetime(df['Date'])
    df['Year'] = df['Date'].dt.year
    df['Month'] = df['Date'].dt.month
    df['Day'] = df['Date'].dt.day
    df['DayOfWeek'] = df['Date'].dt.dayofweek
    
    # Drop Date and ID columns that might not be great for generic ML without massive embedding
    df = df.drop(['Date', 'Store ID', 'Product ID'], axis=1)
    
    # Encode categorical variables
    categorical_cols = ['Category', 'Region', 'Weather Condition', 'Seasonality']
    encoders = {}
    for col in categorical_cols:
        le = LabelEncoder()
        df[col] = le.fit_transform(df[col].astype(str))
        encoders[col] = le
        
    return df, encoders

def train_model(data_path, model_save_path):
    df, encoders = load_and_preprocess_data(data_path)
    
    # Targets and features
    X = df.drop('Demand', axis=1)
    y = df['Demand']
    
    # Train-test split
    print("Splitting data...")
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    
    # Model training
    print("Training RandomForestRegressor model...")
    model = RandomForestRegressor(n_estimators=20, max_depth=10, random_state=42, n_jobs=-1)
    model.fit(X_train, y_train)
    
    # Evaluation
    print("Evaluating model...")
    y_pred = model.predict(X_test)
    mse = mean_squared_error(y_test, y_pred)
    mae = mean_absolute_error(y_test, y_pred)
    r2 = r2_score(y_test, y_pred)
    
    print(f"Mean Squared Error (MSE): {mse:.2f}")
    print(f"Mean Absolute Error (MAE): {mae:.2f}")
    print(f"R-squared (R2): {r2:.2f}")
    
    # Save model and encoders
    print(f"Saving model to {model_save_path}...")
    os.makedirs(os.path.dirname(model_save_path), exist_ok=True)
    joblib.dump({'model': model, 'encoders': encoders}, model_save_path)
    print("Model saved successfully!")
    
if __name__ == "__main__":
    sales_db_path = 'd:/fyp/sales_data.db'
    model_output_path = 'd:/fyp/models/demand_forecast_model.pkl'
    train_model(sales_db_path, model_output_path)
