from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed, FileRequired, MultipleFileField
from wtforms import StringField, PasswordField, BooleanField, SubmitField
from wtforms import TextAreaField, SelectField, FloatField, IntegerField, HiddenField
from wtforms.validators import DataRequired, Email, EqualTo, Length, ValidationError, NumberRange
from wtforms.validators import Regexp, Optional
import re
from flask_login import current_user
from models import User

class LoginForm(FlaskForm):
    """Form for user login"""
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    remember_me = BooleanField('Remember Me')
    submit = SubmitField('Sign In')

class RegistrationForm(FlaskForm):
    """Form for user registration"""
    username = StringField('Username', validators=[
        DataRequired(),
        Length(min=3, max=64, message="Username must be between 3 and 64 characters"),
        Regexp('^[A-Za-z][A-Za-z0-9_.]*$', 0,
               'Usernames must start with a letter and can only contain letters, numbers, dots or underscores')
    ])
    email = StringField('Email', validators=[
        DataRequired(),
        Email(message="Please enter a valid email address"),
        Length(max=120)
    ])
    full_name = StringField('Full Name', validators=[
        Optional(),
        Length(max=128)
    ])
    password = PasswordField('Password', validators=[
        DataRequired(),
        Length(min=8, message="Password must be at least 8 characters long"),
        # Password strength validator
        Regexp(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)', 0,
               'Password must include at least one uppercase letter, one lowercase letter, and one number')
    ])
    password2 = PasswordField('Confirm Password', validators=[
        DataRequired(),
        EqualTo('password', message="Passwords must match")
    ])
    submit = SubmitField('Register')
    
    def validate_username(self, username):
        """Validate username is unique"""
        user = User.query.filter_by(username=username.data).first()
        if user is not None:
            raise ValidationError('Username already taken. Please use a different username.')
    
    def validate_email(self, email):
        """Validate email is unique"""
        user = User.query.filter_by(email=email.data).first()
        if user is not None:
            raise ValidationError('Email already registered. Please use a different email or reset your password.')

class ResetPasswordRequestForm(FlaskForm):
    """Form for requesting password reset"""
    email = StringField('Email', validators=[
        DataRequired(),
        Email(),
        Length(max=120)
    ])
    submit = SubmitField('Request Password Reset')

class ResetPasswordForm(FlaskForm):
    """Form for resetting password after token verification"""
    password = PasswordField('New Password', validators=[
        DataRequired(),
        Length(min=8, message="Password must be at least 8 characters long"),
        Regexp(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)', 0,
               'Password must include at least one uppercase letter, one lowercase letter, and one number')
    ])
    password2 = PasswordField('Confirm Password', validators=[
        DataRequired(),
        EqualTo('password', message="Passwords must match")
    ])
    submit = SubmitField('Reset Password')

class ProfileForm(FlaskForm):
    """Form for editing user profile"""
    full_name = StringField('Full Name', validators=[
        Optional(),
        Length(max=128)
    ])
    email = StringField('Email', validators=[
        DataRequired(),
        Email(),
        Length(max=120)
    ])
    password = PasswordField('New Password (leave blank to keep current)', validators=[
        Optional(),
        Length(min=8, message="Password must be at least 8 characters long"),
        Regexp(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)', 0,
               'Password must include at least one uppercase letter, one lowercase letter, and one number')
    ])
    password2 = PasswordField('Confirm New Password', validators=[
        EqualTo('password', message="Passwords must match")
    ])
    submit = SubmitField('Update Profile')
    
    def validate_email(self, email):
        """Validate email is unique"""
        if email.data != current_user.email:
            user = User.query.filter_by(email=email.data).first()
            if user is not None:
                raise ValidationError('Email already registered. Please use a different email.')

class ResumeAnalysisForm(FlaskForm):
    """Form for resume analysis submission"""
    job_title = StringField('Job Title', validators=[
        DataRequired(),
        Length(max=128)
    ])
    job_description = TextAreaField('Job Description', validators=[
        DataRequired(),
        Length(min=50, message="Job description should be at least 50 characters")
    ])
    resume_files = MultipleFileField('Resume Files', validators=[
        FileRequired(message="Please select at least one resume file"),
        FileAllowed(['pdf', 'doc', 'docx', 'txt'], "Only PDF, DOC, DOCX, and TXT files are allowed")
    ])
    weights_id = SelectField('Scoring Weights', coerce=int)
    submit = SubmitField('Analyze Resumes')
    
    def validate_resume_files(self, resume_files):
        """Validate resume files"""
        if not resume_files.data:
            raise ValidationError('At least one resume file is required')
        
        for file in resume_files.data:
            if file.filename == '':
                raise ValidationError('Please select non-empty files')
            
            extension = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
            if extension not in ['pdf', 'doc', 'docx', 'txt']:
                raise ValidationError(f'File {file.filename} has an invalid extension. Only PDF, DOC, DOCX, and TXT files are allowed.')

class ScoringWeightsForm(FlaskForm):
    """Form for creating or editing scoring weights"""
    name = StringField('Name', validators=[
        DataRequired(),
        Length(max=128)
    ])
    description = TextAreaField('Description', validators=[
        Optional(),
        Length(max=500)
    ])
    
    # Weight fields
    skills_weight = FloatField('Skills Weight', validators=[
        DataRequired(),
        NumberRange(min=0, max=1, message="Weight must be between 0 and 1")
    ])
    education_weight = FloatField('Education Weight', validators=[
        DataRequired(),
        NumberRange(min=0, max=1, message="Weight must be between 0 and 1")
    ])
    experience_weight = FloatField('Experience Weight', validators=[
        DataRequired(),
        NumberRange(min=0, max=1, message="Weight must be between 0 and 1")
    ])
    certifications_weight = FloatField('Certifications Weight', validators=[
        DataRequired(),
        NumberRange(min=0, max=1, message="Weight must be between 0 and 1")
    ])
    
    is_default = BooleanField('Set as Default')
    submit = SubmitField('Save Weights')
    
    def validate_form(self, form):
        """Validate that weights sum to 1.0"""
        total = (form.skills_weight.data + form.education_weight.data + 
                 form.experience_weight.data + form.certifications_weight.data)
        
        if not (0.99 <= total <= 1.01):  # Allow for minor float precision issues
            raise ValidationError('All weights must sum to 1.0')

class ExportResultsForm(FlaskForm):
    """Form for exporting analysis results"""
    format = SelectField('Export Format', choices=[
        ('csv', 'CSV'),
        ('pdf', 'PDF'),
        ('json', 'JSON')
    ])
    analysis_id = HiddenField('Analysis ID')
    submit = SubmitField('Export Results')

