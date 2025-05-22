from flask import Blueprint, render_template, redirect, url_for, flash, request, session, current_app
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from urllib.parse import urlparse
import datetime
import secrets
import os
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature

from models import db, User
from forms import LoginForm, RegistrationForm, ResetPasswordRequestForm, ResetPasswordForm, ProfileForm

# Create Blueprint
auth_bp = Blueprint('auth', __name__)

# Initialize login manager
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Please log in to access this page'
login_manager.login_message_category = 'info'

@login_manager.user_loader
def load_user(user_id):
    """Load user from database by ID"""
    return User.query.get(int(user_id))

def init_login_manager(app):
    """Initialize login manager with app"""
    login_manager.init_app(app)

def generate_confirmation_token(email):
    """Generate token for email confirmation or password reset"""
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    return serializer.dumps(email, salt=current_app.config['SECURITY_PASSWORD_SALT'])

def confirm_token(token, expiration=3600):
    """Confirm token and return email if valid"""
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    try:
        email = serializer.loads(
            token,
            salt=current_app.config['SECURITY_PASSWORD_SALT'],
            max_age=expiration
        )
        return email
    except (SignatureExpired, BadSignature):
        return None

def send_email(to, subject, template):
    """Placeholder for email sending functionality"""
    # In a real application, you would integrate with an email service here
    # For now, we'll just log the email that would be sent
    print(f"Email would be sent to {to} with subject: {subject}")
    print(f"Email content: {template}")
    return True

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Handle user login"""
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user is None or not user.check_password(form.password.data):
            flash('Invalid username or password', 'danger')
            return redirect(url_for('auth.login'))
        
        # User authenticated - update last login and log them in
        user.update_last_login()
        login_user(user, remember=form.remember_me.data)
        
        # Redirect to next page or dashboard
        next_page = request.args.get('next')
        if not next_page or urlparse(next_page).netloc != '':
            next_page = url_for('main.dashboard')
        
        flash(f'Welcome back, {user.username}!', 'success')
        return redirect(next_page)
    
    return render_template('auth/login.html', title='Sign In', form=form)

@auth_bp.route('/logout')
def logout():
    """Handle user logout"""
    logout_user()
    flash('You have been logged out', 'info')
    return redirect(url_for('main.index'))

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    """Handle user registration"""
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    
    form = RegistrationForm()
    if form.validate_on_submit():
        user = User(
            username=form.username.data,
            email=form.email.data,
            password=form.password.data,
            full_name=form.full_name.data
        )
        
        db.session.add(user)
        db.session.commit()
        
        # Generate confirmation token and send email
        token = generate_confirmation_token(user.email)
        confirm_url = url_for('auth.confirm_email', token=token, _external=True)
        html = render_template('auth/activate.html', confirm_url=confirm_url, user=user)
        subject = "Please confirm your email"
        send_email(user.email, subject, html)
        
        flash('A confirmation email has been sent to your inbox.', 'info')
        return redirect(url_for('auth.login'))
    
    return render_template('auth/register.html', title='Register', form=form)

@auth_bp.route('/confirm/<token>')
def confirm_email(token):
    """Confirm user email with token"""
    email = confirm_token(token)
    if not email:
        flash('The confirmation link is invalid or has expired.', 'danger')
        return redirect(url_for('auth.login'))
    
    user = User.query.filter_by(email=email).first()
    if not user:
        flash('Invalid user.', 'danger')
        return redirect(url_for('auth.login'))
    
    if user.is_active:
        flash('Account already confirmed. Please login.', 'info')
    else:
        user.is_active = True
        db.session.commit()
        flash('Your account has been confirmed. You can now login.', 'success')
    
    return redirect(url_for('auth.login'))

@auth_bp.route('/reset-password-request', methods=['GET', 'POST'])
def reset_password_request():
    """Handle password reset request"""
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    
    form = ResetPasswordRequestForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user:
            token = generate_confirmation_token(user.email)
            reset_url = url_for('auth.reset_password', token=token, _external=True)
            html = render_template('auth/reset_password_email.html', reset_url=reset_url, user=user)
            subject = "Password Reset Request"
            send_email(user.email, subject, html)
        
        flash('If an account with that email exists, a password reset link has been sent.', 'info')
        return redirect(url_for('auth.login'))
    
    return render_template('auth/reset_password_request.html', title='Reset Password', form=form)

@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    """Handle password reset with token"""
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    
    email = confirm_token(token)
    if not email:
        flash('The reset link is invalid or has expired.', 'danger')
        return redirect(url_for('auth.login'))
    
    user = User.query.filter_by(email=email).first()
    if not user:
        flash('Invalid user.', 'danger')
        return redirect(url_for('auth.login'))
    
    form = ResetPasswordForm()
    if form.validate_on_submit():
        user.set_password(form.password.data)
        db.session.commit()
        flash('Your password has been reset. You can now login with your new password.', 'success')
        return redirect(url_for('auth.login'))
    
    return render_template('auth/reset_password.html', title='Reset Password', form=form)

@auth_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    """Handle user profile viewing and editing"""
    form = ProfileForm(obj=current_user)
    
    if form.validate_on_submit():
        current_user.full_name = form.full_name.data
        current_user.email = form.email.data
        
        if form.password.data:
            current_user.set_password(form.password.data)
        
        db.session.commit()
        flash('Your profile has been updated.', 'success')
        return redirect(url_for('auth.profile'))
    
    return render_template('auth/profile.html', title='User Profile', form=form)

@auth_bp.route('/users')
@login_required
def users():
    """Admin view for user management"""
    if not current_user.is_admin:
        flash('You do not have permission to access this page', 'danger')
        return redirect(url_for('main.dashboard'))
    
    users = User.query.all()
    return render_template('auth/users.html', title='User Management', users=users)

@auth_bp.route('/user/<int:user_id>/toggle-active', methods=['POST'])
@login_required
def toggle_user_active(user_id):
    """Toggle user active status (admin only)"""
    if not current_user.is_admin:
        flash('You do not have permission to perform this action', 'danger')
        return redirect(url_for('main.dashboard'))
    
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('You cannot deactivate your own account', 'danger')
    else:
        user.is_active = not user.is_active
        db.session.commit()
        status = 'activated' if user.is_active else 'deactivated'
        flash(f'User {user.username} has been {status}', 'success')
    
    return redirect(url_for('auth.users'))

