import os
import re
import random
import time
import uuid
import json
import shutil
import logging
import datetime
from pathlib import Path
from functools import wraps
from io import BytesIO
import csv
import tempfile

from flask import Flask, request, render_template, redirect, url_for, flash, session, jsonify, send_file, abort
from flask_wtf.csrf import CSRFProtect
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_mail import Mail, Message
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.utils import secure_filename
from werkzeug.exceptions import RequestEntityTooLarge, Forbidden, NotFound
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import nltk
from nltk.corpus import stopwords
from nltk.tokenize import word_tokenize
from nltk.stem import WordNetLemmatizer
import string
import pandas as pd

# Local imports
from models import db, User, ResumeAnalysis, ResumeFile, ScoringWeights, initialize_db
from auth import auth_bp, init_login_manager
from forms import LoginForm, RegistrationForm, ResetPasswordRequestForm, ResetPasswordForm
from forms import ProfileForm, ResumeAnalysisForm, ScoringWeightsForm, ExportResultsForm
from utils import extract_text_from_file

# Create Flask application
app = Flask(__name__)

@app.context_processor
def utility_processor():
    def now():
        return datetime.datetime.now()
    return dict(now=now)

# Load configuration
app.config.from_mapping(
    SECRET_KEY=os.environ.get('SECRET_KEY', 'dev_key_replace_in_production'),
    SECURITY_PASSWORD_SALT=os.environ.get('SECURITY_PASSWORD_SALT', 'salt_replace_in_production'),
    UPLOAD_FOLDER='uploads/',
    MAX_CONTENT_LENGTH=10 * 1024 * 1024,  # 10 MB max file size
    ALLOWED_EXTENSIONS={'pdf', 'doc', 'docx', 'txt'},
    SESSION_TIMEOUT=3600,  # 1 hour in seconds
    MAIL_SERVER=os.environ.get('MAIL_SERVER', 'smtp.example.com'),
    MAIL_PORT=int(os.environ.get('MAIL_PORT', 587)),
    MAIL_USE_TLS=os.environ.get('MAIL_USE_TLS', 'True').lower() in ('true', 'yes', '1'),
    MAIL_USERNAME=os.environ.get('MAIL_USERNAME', 'user@example.com'),
    MAIL_PASSWORD=os.environ.get('MAIL_PASSWORD', 'password'),
    MAIL_DEFAULT_SENDER=os.environ.get('MAIL_DEFAULT_SENDER', 'Resume Analyzer <noreply@resumeanalyzer.com>'),
    RESULTS_PER_PAGE=10
)

# Configure logging
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join('logs', 'app.log'), encoding='utf-8')
    ]
)
logger = logging.getLogger('resume_analyzer')

# Ensure the logs and uploads directories exist
for directory in ['logs', app.config['UPLOAD_FOLDER']]:
    if not os.path.exists(directory):
        os.makedirs(directory)

# Download required NLTK resources
try:
    nltk.download('punkt', quiet=True)
    nltk.download('stopwords', quiet=True)
    nltk.download('wordnet', quiet=True)
except Exception as e:
    logger.error(f"NLTK download error: {e}")

# Initialize extensions
csrf = CSRFProtect(app)
mail = Mail(app)
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

# Register blueprints
app.register_blueprint(auth_bp, url_prefix='/auth')

# Initialize database
initialize_db(app)

# Initialize login manager
init_login_manager(app)

# Admin required decorator
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('You do not have permission to access this page', 'danger')
            return redirect(url_for('main.index'))
        return f(*args, **kwargs)
    return decorated_function

# Helper Functions
def allowed_file(filename):
    """Check if file has an allowed extension"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def clean_old_uploads():
    """Clean up upload files older than the session timeout"""
    try:
        current_time = time.time()
        timeout = app.config['SESSION_TIMEOUT']
        
        for file_path in Path(app.config['UPLOAD_FOLDER']).glob('*'):
            # Skip directories
            if file_path.is_dir():
                continue
                
            # Check file age
            file_age = current_time - file_path.stat().st_mtime
            if file_age > timeout:
                os.remove(file_path)
                logger.info(f"Removed old file: {file_path}")
    except Exception as e:
        logger.error(f"Error cleaning old uploads: {e}")

def send_email(to, subject, template):
    """Send an email using Flask-Mail"""
    try:
        msg = Message(
            subject,
            recipients=[to],
            html=template,
            sender=app.config['MAIL_DEFAULT_SENDER']
        )
        mail.send(msg)
        logger.info(f"Email sent to {to}: {subject}")
        return True
    except Exception as e:
        logger.error(f"Error sending email: {e}")
        return False

def preprocess_text(text):
    """
    Preprocess text by performing:
    1. Lowercase conversion
    2. Punctuation removal
    3. Stopword removal
    4. Lemmatization
    """
    if not text:
        return ""
    
    try:
        # Convert to lowercase
        text = text.lower()
        
        # Remove punctuation
        text = text.translate(str.maketrans('', '', string.punctuation))
        
        # Remove numbers
        text = re.sub(r'\d+', '', text)
        
        # Simple word tokenization
        tokens = text.split()
        
        # Remove stopwords
        stop_words = set(stopwords.words('english'))
        filtered_tokens = [w for w in tokens if not w in stop_words]
        
        # Lemmatize
        lemmatizer = WordNetLemmatizer()
        lemmatized_tokens = [lemmatizer.lemmatize(token) for token in filtered_tokens]
        
        # Join tokens back into text
        return ' '.join(lemmatized_tokens)
    except Exception as e:
        logger.error(f"Error preprocessing text: {e}")
        return text  # Return original text if preprocessing fails

def calculate_similarity(resume_text, job_description, weights=None):
    """
    Calculate similarity between resume text and job description using:
    1. TF-IDF vectorization
    2. Cosine similarity
    3. Optional scoring weights
    """
    try:
        if not resume_text or not job_description:
            return 0.0
        
        documents = [resume_text, job_description]
        
        # Default weights if none provided
        if weights is None:
            weights = {
                'skills': 0.4,
                'education': 0.2,
                'experience': 0.3,
                'certifications': 0.1
            }
        
        # TF-IDF with advanced parameters
        vectorizer = TfidfVectorizer(
            max_features=10000,  # Limit features to improve performance
            min_df=1,           # Minimum document frequency
            max_df=0.95,         # Maximum document frequency
            ngram_range=(1, 2),  # Use unigrams and bigrams
            stop_words='english' # Built-in stopwords
        )
        
        tfidf_matrix = vectorizer.fit_transform(documents)
        
        # Calculate cosine similarity
        base_similarity = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]
        
        # Apply weights if document sections are identified
        # This is a simplified approach; in a real implementation, you'd need to identify
        # document sections more robustly
        final_score = base_similarity
        
        return max(0.0, min(final_score, 1.0))  # Constrain between 0 and 1
    except Exception as e:
        logger.error(f"Error calculating similarity: {e}")
        return 0.0  # Return 0 similarity on error

def export_results_as_csv(analysis):
    """Export analysis results as CSV file"""
    try:
        results = analysis.get_results()
        resume_files = analysis.resume_files.all()
        
        # Create a temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.csv') as tmp:
            # Create CSV writer
            csv_file = open(tmp.name, 'w', newline='')
            writer = csv.writer(csv_file)
            
            # Write header
            writer.writerow(['Filename', 'Score', 'File Type', 'Date Analyzed'])
            
            # Write data rows
            for result in results:
                filename, score = result
                file_obj = next((f for f in resume_files if f.original_filename == filename), None)
                if file_obj:
                    writer.writerow([
                        filename,
                        f"{score:.2f}",
                        file_obj.file_type,
                        file_obj.created_at.strftime('%Y-%m-%d %H:%M:%S')
                    ])
            
            csv_file.close()
            
            return tmp.name
    except Exception as e:
        logger.error(f"Error exporting results as CSV: {e}")
        return None

# Error handlers
@app.errorhandler(404)
def page_not_found(e):
    return render_template('errors/404.html'), 404

@app.errorhandler(500)
def internal_server_error(e):
    logger.error(f"Internal server error: {e}")
    return render_template('errors/500.html'), 500

@app.errorhandler(413)
@app.errorhandler(RequestEntityTooLarge)
def request_entity_too_large(error):
    flash('File too large. Maximum size is 10MB', 'danger')
    return render_template('errors/413.html'), 413

@app.errorhandler(403)
def forbidden(error):
    return render_template('errors/403.html'), 403

# Main Blueprint
from flask import Blueprint
main_bp = Blueprint('main', __name__)

# Index / Landing Page
@main_bp.route('/')
def index():
    """Landing page - redirects to dashboard if logged in"""
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return render_template('index.html', title="Welcome to Resume Analyzer")

# Dashboard
@main_bp.route('/dashboard')
@login_required
def dashboard():
    """Dashboard with user statistics and recent analyses"""
    # Get recent analyses
    recent_analyses = ResumeAnalysis.query.filter_by(user_id=current_user.id) \
                                .order_by(ResumeAnalysis.created_at.desc()) \
                                .limit(5).all()
    
    # Get user statistics
    total_analyses = ResumeAnalysis.query.filter_by(user_id=current_user.id).count()
    total_resumes = db.session.query(db.func.count(ResumeFile.id)) \
                             .join(ResumeAnalysis) \
                             .filter(ResumeAnalysis.user_id == current_user.id) \
                             .scalar() or 0
    
    # If admin, get system-wide statistics
    if current_user.is_admin:
        user_count = User.query.count()
        active_users = User.query.filter_by(is_active=True).count()
        inactive_users = user_count - active_users
        total_system_analyses = ResumeAnalysis.query.count()
        
        admin_stats = {
            'user_count': user_count,
            'active_users': active_users,
            'inactive_users': inactive_users,
            'total_system_analyses': total_system_analyses
        }
    else:
        admin_stats = None
    
    return render_template('dashboard.html', 
                          title="Dashboard",
                          recent_analyses=recent_analyses,
                          total_analyses=total_analyses,
                          total_resumes=total_resumes,
                          admin_stats=admin_stats,
                          days_active=(datetime.datetime.now() - current_user.created_at).days)

# Analyze Resumes
@main_bp.route('/analyze', methods=['GET', 'POST'])
@login_required
def analyze():
    """Resume analysis page"""
    form = ResumeAnalysisForm()
    
    # Load user's scoring weights for the dropdown
    weights = ScoringWeights.query.filter_by(user_id=current_user.id).all()
    system_weights = ScoringWeights.query.filter_by(is_default=True).first()
    
    if system_weights and system_weights not in weights:
        weights.append(system_weights)
    
    form.weights_id.choices = [(w.id, w.name) for w in weights]
    
    if form.validate_on_submit():
        try:
            # Create analysis record
            analysis = ResumeAnalysis(
                user_id=current_user.id,
                job_description=form.job_description.data,
                job_title=form.job_title.data
            )
            db.session.add(analysis)
            db.session.flush()  # Get the analysis ID
            
            # Get selected weights
            selected_weights = ScoringWeights.query.get(form.weights_id.data)
            weights_dict = selected_weights.get_weights() if selected_weights else None
            
            # Process resume files
            results = []
            files = request.files.getlist('resume_files')
            
            for file in files:
                if file and file.filename and allowed_file(file.filename):
                    # Secure filename and create unique file path
                    filename = secure_filename(file.filename)
                    unique_filename = f"{analysis.session_id}_{filename}"
                    file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
                    
                    # Get file size and type
                    file.save(file_path)
                    file_size = os.path.getsize(file_path)
                    file_type = file.filename.rsplit('.', 1)[1].lower()
                    
                    # Create resume file record
                    resume_file = ResumeFile(
                        analysis_id=analysis.id,
                        original_filename=filename,
                        stored_filename=unique_filename,
                        file_size=file_size,
                        file_type=file_type
                    )
                    db.session.add(resume_file)
                    
                    # Extract and preprocess text
                    try:
                        # Extract text from file
                        resume_text = extract_text_from_file(file_path)
                        resume_file.extracted_text = resume_text  # Store the extracted text
                        
                        # Preprocess text
                        processed_resume = preprocess_text(resume_text)
                        processed_job = preprocess_text(form.job_description.data)
                        
                        # Calculate similarity
                        score = calculate_similarity(processed_resume, processed_job, weights_dict)
                        resume_file.score = score
                        
                        # Add to results
                        results.append((filename, score))
                    except Exception as e:
                        logger.error(f"Error processing file {filename}: {e}")
                        db.session.delete(resume_file)  # Remove the record if processing fails
            
            if not results:
                flash('No valid resume files were processed', 'warning')
                return redirect(url_for('main.analyze'))
            
            # Save results and commit
            analysis.set_results(results)
            db.session.commit()
            
            flash('Resume analysis completed successfully!', 'success')
            return redirect(url_for('main.analysis_results', analysis_id=analysis.id))
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error during analysis: {e}")
            flash(f'An error occurred during analysis: {str(e)}', 'danger')
    
    return render_template('analyze.html', form=form, title="Analyze Resumes")

# Analysis Results
@main_bp.route('/analysis/<int:analysis_id>')
@login_required
def analysis_results(analysis_id):
    """View results of a specific analysis"""
    analysis = ResumeAnalysis.query.get_or_404(analysis_id)
    
    # Ensure the user can only access their own analyses unless they're an admin
    if analysis.user_id != current_user.id and not current_user.is_admin:
        flash('You do not have permission to view this analysis', 'danger')
        return redirect(url_for('main.dashboard'))
    
    # Get resume files
    resume_files = analysis.resume_files.all()
    
    # Get results
    results = analysis.get_results()
    
    # Prepare export form
    export_form = ExportResultsForm()
    export_form.analysis_id.data = analysis_id
    
    return render_template('results.html', 
                          title=f"Analysis Results: {analysis.job_title}",
                          analysis=analysis,
                          results=results,
                          resume_files=resume_files,
                          export_form=export_form,
                          now=datetime.datetime.now())

# Export Results
@main_bp.route('/export_analysis', methods=['POST'])
@login_required
def export_analysis():
    """Export analysis results in different formats"""
    form = ExportResultsForm()
    
    if form.validate_on_submit():
        analysis_id = form.analysis_id.data
        export_format = form.format.data
        
        analysis = ResumeAnalysis.query.get_or_404(analysis_id)
        
        # Ensure the user can only export their own analyses unless they're an admin
        if analysis.user_id != current_user.id and not current_user.is_admin:
            flash('You do not have permission to export this analysis', 'danger')
            return redirect(url_for('main.dashboard'))
        
        try:
            if export_format == 'csv':
                # Export as CSV
                csv_file = export_results_as_csv(analysis)
                if csv_file:
                    return send_file(
                        csv_file,
                        as_attachment=True,
                        download_name=f"analysis_{analysis_id}_{datetime.datetime.now().strftime('%Y%m%d')}.csv",
                        mimetype='text/csv'
                    )
            elif export_format == 'json':
                # Export as JSON
                data = {
                    'analysis_id': analysis.id,
                    'job_title': analysis.job_title,
                    'created_at': analysis.created_at.isoformat(),
                    'results': analysis.get_results()
                }
                return jsonify(data)
            else:
                flash(f'Export format {export_format} is not supported', 'warning')
                
        except Exception as e:
            logger.error(f"Error exporting analysis: {e}")
            flash(f'Error exporting analysis: {str(e)}', 'danger')
    
    return redirect(url_for('main.analysis_results', analysis_id=form.analysis_id.data))

# History
@main_bp.route('/history')
@login_required
def history():
    """View analysis history"""
    page = request.args.get('page', 1, type=int)
    per_page = app.config['RESULTS_PER_PAGE']
    
    if current_user.is_admin and request.args.get('all'):
        # Admin can view all analyses
        analyses = ResumeAnalysis.query.order_by(ResumeAnalysis.created_at.desc())
    else:
        # Regular users can only view their own analyses
        analyses = ResumeAnalysis.query.filter_by(user_id=current_user.id) \
                              .order_by(ResumeAnalysis.created_at.desc())
    
    # Paginate results
    paginated_analyses = analyses.paginate(page=page, per_page=per_page)
    
    return render_template('history.html',
                          title="Analysis History",
                          analyses=paginated_analyses)

# Scoring Weights
@main_bp.route('/weights')
@login_required
def weights():
    """View and manage scoring weights"""
    # Get user's weights
    user_weights = ScoringWeights.query.filter_by(user_id=current_user.id).all()
    
    # Get system default weights
    system_weights = ScoringWeights.query.filter_by(is_default=True).all()
    
    return render_template('weights.html',
                          title="Scoring Weights",
                          user_weights=user_weights,
                          system_weights=system_weights)

# Create or Edit Weights
@main_bp.route('/weights/edit/<int:weight_id>', methods=['GET', 'POST'])
@main_bp.route('/weights/create', methods=['GET', 'POST'])
@login_required
def edit_weights(weight_id=None):
    """Create or edit scoring weights"""
    # Initialize form
    form = ScoringWeightsForm()
    
    # If editing existing weights
    if weight_id:
        weights = ScoringWeights.query.get_or_404(weight_id)
        
        # Ensure the user can only edit their own weights unless they're an admin
        if weights.user_id != current_user.id and not current_user.is_admin:
            flash('You do not have permission to edit these weights', 'danger')
            return redirect(url_for('main.weights'))
        
        if request.method == 'GET':
            # Pre-populate form
            form.name.data = weights.name
            form.description.data = weights.description
            form.is_default.data = weights.is_default
            
            # Load weights
            weight_dict = weights.get_weights()
            form.skills_weight.data = weight_dict.get('skills', 0.4)
            form.education_weight.data = weight_dict.get('education', 0.2)
            form.experience_weight.data = weight_dict.get('experience', 0.3)
            form.certifications_weight.data = weight_dict.get('certifications', 0.1)
    else:
        weights = None
    
    if form.validate_on_submit():
        try:
            # Check weights sum to 1.0
            total = (form.skills_weight.data + form.education_weight.data + 
                     form.experience_weight.data + form.certifications_weight.data)
            
            if not (0.99 <= total <= 1.01):  # Allow for minor float precision issues
                flash('All weights must sum to 1.0', 'danger')
                return render_template('edit_weights.html', form=form, weights=weights,
                                      title="Edit Weights" if weight_id else "Create Weights")
            
            # Prepare weights dictionary
            weights_dict = {
                'skills': form.skills_weight.data,
                'education': form.education_weight.data,
                'experience': form.experience_weight.data,
                'certifications': form.certifications_weight.data
            }
            
            # If creating new weights
            if not weights:
                weights = ScoringWeights(
                    user_id=current_user.id,
                    name=form.name.data,
                    weights_dict=weights_dict,
                    description=form.description.data,
                    is_default=False  # New weights are not default by default
                )
                db.session.add(weights)
                flash('New scoring weights created successfully!', 'success')
            else:
                # Update existing weights
                weights.name = form.name.data
                weights.description = form.description.data
                weights.set_weights(weights_dict)
                flash('Scoring weights updated successfully!', 'success')
            
            # If setting as default, update all others
            if form.is_default.data and not weights.is_default:
                # First unset all defaults for this user
                user_defaults = ScoringWeights.query.filter_by(
                    user_id=current_user.id, 
                    is_default=True
                ).all()
                
                for default in user_defaults:
                    default.is_default = False
                
                # Set this one as default
                weights.is_default = True
                flash('This scoring weight set is now your default.', 'info')
            
            db.session.commit()
            return redirect(url_for('main.weights'))
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error saving weights: {e}")
            flash(f'An error occurred: {str(e)}', 'danger')
    
    return render_template('edit_weights.html', 
                          form=form, 
                          weights=weights,
                          title="Edit Weights" if weight_id else "Create Weights")

# Delete Weights
@main_bp.route('/weights/delete/<int:weight_id>', methods=['POST'])
@login_required
def delete_weights(weight_id):
    """Delete scoring weights"""
    weights = ScoringWeights.query.get_or_404(weight_id)
    
    # Ensure the user can only delete their own weights unless they're an admin
    if weights.user_id != current_user.id and not current_user.is_admin:
        flash('You do not have permission to delete these weights', 'danger')
        return redirect(url_for('main.weights'))
    
    # Prevent deletion of system default weights if not admin
    if weights.is_default and (weights.user_id != current_user.id) and not current_user.is_admin:
        flash('You cannot delete system default weights', 'danger')
        return redirect(url_for('main.weights'))
    
    try:
        name = weights.name
        db.session.delete(weights)
        db.session.commit()
        flash(f'Scoring weights "{name}" deleted successfully', 'success')
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting weights: {e}")
        flash(f'An error occurred: {str(e)}', 'danger')
    
    return redirect(url_for('main.weights'))

# Set Default Weights
@main_bp.route('/weights/set_default/<int:weight_id>', methods=['POST'])
@login_required
def set_default_weights(weight_id):
    """Set weights as default"""
    weights = ScoringWeights.query.get_or_404(weight_id)
    
    # Ensure the user can only set their own weights as default unless they're an admin
    if weights.user_id != current_user.id and not current_user.is_admin:
        flash('You do not have permission to modify these weights', 'danger')
        return redirect(url_for('main.weights'))
    
    try:
        # First unset all defaults for this user
        user_defaults = ScoringWeights.query.filter_by(
            user_id=current_user.id, 
            is_default=True
        ).all()
        
        for default in user_defaults:
            default.is_default = False
        
        # Set this one as default
        weights.is_default = True
        db.session.commit()
        
        flash(f'"{weights.name}" is now your default scoring weight set', 'success')
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error setting default weights: {e}")
        flash(f'An error occurred: {str(e)}', 'danger')
    
    return redirect(url_for('main.weights'))

# API route for checking weights validation via AJAX
@main_bp.route('/api/validate_weights', methods=['POST'])
@login_required
def validate_weights():
    """Validate that weights sum to 1.0"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'valid': False, 'message': 'No data provided'})
        
        skills = float(data.get('skills', 0))
        education = float(data.get('education', 0))
        experience = float(data.get('experience', 0))
        certifications = float(data.get('certifications', 0))
        
        total = skills + education + experience + certifications
        
        # Allow for minor float precision issues
        valid = 0.99 <= total <= 1.01
        
        return jsonify({
            'valid': valid,
            'total': round(total, 2),
            'message': 'Weights sum to 1.0' if valid else 'Weights must sum to 1.0'
        })
    except Exception as e:
        logger.error(f"Error validating weights: {e}")
        return jsonify({'valid': False, 'message': 'Error validating weights'})

# Register main blueprint
app.register_blueprint(main_bp)

# Periodic cleanup task (runs before each request)
@app.before_request
def before_request():
    """Run tasks before each request"""
    try:
        # Clean old uploads with a small probability to avoid doing it on every request
        if random.random() < 0.01:  # ~1% chance
            clean_old_uploads()
    except Exception as e:
        logger.error(f"Error in before_request: {e}")

# Application startup
if __name__ == '__main__':
    # Ensure required directories exist
    for directory in ['logs', app.config['UPLOAD_FOLDER'], 'instance']:
        if not os.path.exists(directory):
            os.makedirs(directory)
    
    # Set up debug mode based on environment
    debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() in ('true', 'yes', '1')
    
    # Get host and port from environment or use defaults
    host = os.environ.get('FLASK_HOST', '0.0.0.0')
    port = int(os.environ.get('FLASK_PORT', 5000))
    
    # Run the application
    app.run(host=host, port=port, debug=debug_mode)
