import os
import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import json
import uuid

# Initialize SQLAlchemy
db = SQLAlchemy()

class User(UserMixin, db.Model):
    """User model for authentication and profile management"""
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, index=True, nullable=False)
    email = db.Column(db.String(120), unique=True, index=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    full_name = db.Column(db.String(128))
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    last_login = db.Column(db.DateTime)
    is_active = db.Column(db.Boolean, default=True)
    is_admin = db.Column(db.Boolean, default=False)
    
    # Relationships
    analyses = db.relationship('ResumeAnalysis', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    scoring_weights = db.relationship('ScoringWeights', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    
    def __init__(self, username, email, password, full_name=None, is_admin=False):
        self.username = username
        self.email = email
        self.set_password(password)
        self.full_name = full_name
        self.is_admin = is_admin
    
    def set_password(self, password):
        """Set user password using secure hash"""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """Check password against stored hash"""
        return check_password_hash(self.password_hash, password)
    
    def update_last_login(self):
        """Update last login timestamp"""
        self.last_login = datetime.datetime.utcnow()
        db.session.commit()
    
    def to_dict(self):
        """Convert user to dictionary for serialization"""
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'full_name': self.full_name,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login': self.last_login.isoformat() if self.last_login else None
        }
    
    def __repr__(self):
        return f'<User {self.username}>'


class ResumeAnalysis(db.Model):
    """Model for storing resume analysis results"""
    __tablename__ = 'resume_analyses'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    job_title = db.Column(db.String(128))
    job_description = db.Column(db.Text, nullable=False)
    session_id = db.Column(db.String(64), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    
    # Results are stored as JSON for flexibility
    results = db.Column(db.Text)
    best_match_file = db.Column(db.String(256))
    best_match_score = db.Column(db.Float)
    
    # Relationships
    resume_files = db.relationship('ResumeFile', backref='analysis', lazy='dynamic', cascade='all, delete-orphan')
    
    def __init__(self, user_id, job_description, job_title=None):
        self.user_id = user_id
        self.job_description = job_description
        self.job_title = job_title
        self.session_id = str(uuid.uuid4())
    
    def set_results(self, results_list):
        """Store results as JSON string"""
        self.results = json.dumps(results_list)
        
        # Set best match if available
        if results_list:
            best_match = max(results_list, key=lambda x: x[1])
            self.best_match_file = best_match[0]
            self.best_match_score = best_match[1]
    
    def get_results(self):
        """Get results as Python list"""
        if self.results:
            return json.loads(self.results)
        return []
    
    def to_dict(self):
        """Convert analysis to dictionary for serialization"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'job_title': self.job_title,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'best_match_file': self.best_match_file,
            'best_match_score': self.best_match_score,
            'resume_count': self.resume_files.count(),
            'results': self.get_results()
        }
    
    def __repr__(self):
        return f'<ResumeAnalysis {self.id}: {self.job_title}>'


class ResumeFile(db.Model):
    """Model for storing resume file information"""
    __tablename__ = 'resume_files'
    
    id = db.Column(db.Integer, primary_key=True)
    analysis_id = db.Column(db.Integer, db.ForeignKey('resume_analyses.id'), nullable=False)
    original_filename = db.Column(db.String(256), nullable=False)
    stored_filename = db.Column(db.String(256), nullable=False)
    file_size = db.Column(db.Integer)  # Size in bytes
    file_type = db.Column(db.String(32))
    score = db.Column(db.Float)
    extracted_text = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    
    def __init__(self, analysis_id, original_filename, stored_filename, file_size=None, file_type=None):
        self.analysis_id = analysis_id
        self.original_filename = original_filename
        self.stored_filename = stored_filename
        self.file_size = file_size
        self.file_type = file_type
    
    def to_dict(self):
        """Convert file to dictionary for serialization"""
        return {
            'id': self.id,
            'analysis_id': self.analysis_id,
            'original_filename': self.original_filename,
            'file_size': self.file_size,
            'file_type': self.file_type,
            'score': self.score,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
    
    def __repr__(self):
        return f'<ResumeFile {self.original_filename}: {self.score}>'


class ScoringWeights(db.Model):
    """Model for storing custom scoring weights"""
    __tablename__ = 'scoring_weights'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name = db.Column(db.String(128), nullable=False)
    description = db.Column(db.Text)
    is_default = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    
    # Store weights as JSON for flexibility
    weights = db.Column(db.Text, nullable=False)
    
    def __init__(self, user_id, name, weights_dict, description=None, is_default=False):
        self.user_id = user_id
        self.name = name
        self.set_weights(weights_dict)
        self.description = description
        self.is_default = is_default
    
    def set_weights(self, weights_dict):
        """Store weights as JSON string"""
        self.weights = json.dumps(weights_dict)
    
    def get_weights(self):
        """Get weights as Python dictionary"""
        if self.weights:
            return json.loads(self.weights)
        return {}
    
    def to_dict(self):
        """Convert weights to dictionary for serialization"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'name': self.name,
            'description': self.description,
            'is_default': self.is_default,
            'weights': self.get_weights(),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
    
    def __repr__(self):
        return f'<ScoringWeights {self.name}>'


def initialize_db(app):
    """Initialize the database with the Flask app"""
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
        'DATABASE_URL', 'sqlite:///' + os.path.join(app.instance_path, 'resume_analyzer.db'))
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # Ensure the instance folder exists
    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass
    
    db.init_app(app)
    
    # Create tables
    with app.app_context():
        db.create_all()
        
        # Create admin user if none exists
        if User.query.filter_by(is_admin=True).first() is None:
            admin_password = os.environ.get('ADMIN_PASSWORD', 'admin')
            admin_user = User(
                username='admin',
                email='admin@example.com',
                password=admin_password,
                full_name='Administrator',
                is_admin=True
            )
            db.session.add(admin_user)
            
            # Create default scoring weights
            default_weights = ScoringWeights(
                user_id=1,  # Admin user
                name='Default Weights',
                weights_dict={
                    'skills': 0.4,
                    'education': 0.2,
                    'experience': 0.3,
                    'certifications': 0.1
                },
                description='Default scoring weights for resume analysis',
                is_default=True
            )
            db.session.add(default_weights)
            
            db.session.commit()

