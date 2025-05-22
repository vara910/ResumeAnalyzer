#!/usr/bin/env python3
"""
Resume Analyzer Initialization Script
This script initializes the Resume Analyzer application by:
1. Setting up directory structure
2. Creating database and tables
3. Creating admin user
4. Setting up default configurations
"""

import os
import sys
import logging
import getpass
from pathlib import Path
from flask import Flask
from werkzeug.security import generate_password_hash

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('init')

def create_app_structure():
    """Create necessary directories if they don't exist"""
    logger.info("Creating application directory structure...")
    
    # Define directories to create
    directories = [
        'uploads',
        'logs',
        'instance',
        'templates/errors'
    ]
    
    # Create each directory
    for directory in directories:
        path = Path(directory)
        if not path.exists():
            path.mkdir(parents=True)
            logger.info(f"Created directory: {directory}")
        else:
            logger.info(f"Directory already exists: {directory}")
    
    return True

def initialize_database(app):
    """Initialize database and create tables"""
    logger.info("Initializing database...")
    
    # Import here to avoid circular imports
    from models import db, User, ScoringWeights, initialize_db
    
    try:
        # Initialize database with app
        initialize_db(app)
        logger.info("Database initialized successfully.")
        return True
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        return False

def create_admin_user(app):
    """Create admin user if none exists"""
    logger.info("Checking for admin user...")
    
    from models import db, User
    
    with app.app_context():
        # Check if admin user exists
        admin = User.query.filter_by(is_admin=True).first()
        if admin:
            logger.info(f"Admin user already exists: {admin.username}")
            return True
        
        # Create admin user
        try:
            print("\n=== Admin User Creation ===")
            username = input("Enter admin username [admin]: ") or "admin"
            email = input("Enter admin email [admin@example.com]: ") or "admin@example.com"
            password = getpass.getpass("Enter admin password [admin]: ") or "admin"
            
            admin = User(
                username=username,
                email=email,
                password=password,
                full_name="Administrator",
                is_admin=True
            )
            
            db.session.add(admin)
            db.session.commit()
            
            logger.info(f"Admin user created successfully: {username}")
            return True
        except Exception as e:
            logger.error(f"Admin user creation failed: {e}")
            db.session.rollback()
            return False

def create_default_weights(app):
    """Create default scoring weights"""
    logger.info("Setting up default scoring weights...")
    
    from models import db, ScoringWeights, User
    
    with app.app_context():
        # Check if default weights exist
        default_weights = ScoringWeights.query.filter_by(is_default=True).first()
        if default_weights:
            logger.info("Default weights already exist.")
            return True
        
        # Get admin user
        admin = User.query.filter_by(is_admin=True).first()
        if not admin:
            logger.error("Admin user not found. Cannot create default weights.")
            return False
        
        # Create default weights
        try:
            weights = ScoringWeights(
                user_id=admin.id,
                name="Default Weights",
                weights_dict={
                    'skills': 0.4,
                    'education': 0.2,
                    'experience': 0.3,
                    'certifications': 0.1
                },
                description="Default scoring weights for resume analysis",
                is_default=True
            )
            
            db.session.add(weights)
            db.session.commit()
            
            logger.info("Default scoring weights created successfully.")
            return True
        except Exception as e:
            logger.error(f"Default weights creation failed: {e}")
            db.session.rollback()
            return False

def setup_configuration(app):
    """Setup application configuration"""
    logger.info("Setting up application configuration...")
    
    # Basic configuration
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev_key_replace_in_production')
    app.config['SECURITY_PASSWORD_SALT'] = os.environ.get('SECURITY_PASSWORD_SALT', 'salt_replace_in_production')
    app.config['UPLOAD_FOLDER'] = 'uploads/'
    app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10 MB max file size
    app.config['ALLOWED_EXTENSIONS'] = {'pdf', 'doc', 'docx', 'txt'}
    app.config['SESSION_TIMEOUT'] = 3600  # 1 hour in seconds
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # Email configuration
    app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', 'smtp.example.com')
    app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 587))
    app.config['MAIL_USE_TLS'] = os.environ.get('MAIL_USE_TLS', 'True').lower() in ('true', 'yes', '1')
    app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME', 'user@example.com')
    app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD', 'password')
    app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_DEFAULT_SENDER', 'Resume Analyzer <noreply@resumeanalyzer.com>')
    
    logger.info("Application configuration set up successfully.")
    return True

def main():
    """Main initialization function"""
    print("=" * 80)
    print("Resume Analyzer - Initialization Script")
    print("=" * 80)
    
    # Create Flask app
    app = Flask(__name__)
    
    # Setup steps
    steps = [
        ("Creating directory structure", create_app_structure),
        ("Setting up configuration", lambda: setup_configuration(app)),
        ("Initializing database", lambda: initialize_database(app)),
        ("Creating admin user", lambda: create_admin_user(app)),
        ("Setting up default weights", lambda: create_default_weights(app))
    ]
    
    # Execute each step
    success = True
    for step_name, step_func in steps:
        print(f"\nExecuting: {step_name}...")
        if step_func():
            print(f"✓ {step_name} completed successfully.")
        else:
            print(f"✗ {step_name} failed.")
            success = False
            break
    
    # Final message
    if success:
        print("\n" + "=" * 80)
        print("Initialization completed successfully!")
        print("You can now run the application with: python app.py")
        print("=" * 80)
        return 0
    else:
        print("\n" + "=" * 80)
        print("Initialization failed. Please check the logs and try again.")
        print("=" * 80)
        return 1

if __name__ == "__main__":
    sys.exit(main())

