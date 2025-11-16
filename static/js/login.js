// Login page JavaScript

document.addEventListener('DOMContentLoaded', function() {
    const emailForm = document.getElementById('emailForm');
    const codeForm = document.getElementById('codeForm');
    const emailStep = document.getElementById('emailStep');
    const codeStep = document.getElementById('codeStep');
    const emailInput = document.getElementById('emailInput');
    const codeInput = document.getElementById('codeInput');
    const sendCodeBtn = document.getElementById('sendCodeBtn');
    const verifyCodeBtn = document.getElementById('verifyCodeBtn');
    const backToEmailBtn = document.getElementById('backToEmailBtn');
    const errorMessage = document.getElementById('errorMessage');
    const successMessage = document.getElementById('successMessage');
    const loadingSpinner = document.getElementById('loadingSpinner');
    const loadingText = document.getElementById('loadingText');
    const emailDisplay = document.getElementById('emailDisplay');
    
    let userEmail = '';

    // Email form submission
    emailForm.addEventListener('submit', async function(e) {
        e.preventDefault();
        
        const email = emailInput.value.trim().toLowerCase();
        
        if (!email || !email.includes('@')) {
            showError('Please enter a valid email address');
            return;
        }

        userEmail = email;
        setLoading(true, 'Sending security code...');
        hideMessages();

        try {
            const response = await fetch('/api/login/send-code', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ email: email })
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.error || 'Failed to send code');
            }

            // Show success message (or dev code if in development)
            if (data.dev_code) {
                showSuccess(`Development mode: Use code ${data.dev_code}`);
            } else {
                showSuccess('Security code sent! Check your email.');
            }

            // Switch to code verification step
            emailStep.style.display = 'none';
            codeStep.style.display = 'block';
            emailDisplay.textContent = email;
            codeInput.focus();

        } catch (error) {
            console.error('Error sending code:', error);
            showError(error.message || 'Failed to send security code. Please try again.');
        } finally {
            setLoading(false);
        }
    });

    // Code form submission
    codeForm.addEventListener('submit', async function(e) {
        e.preventDefault();
        
        const code = codeInput.value.trim();
        const zipcode = document.getElementById('zipcodeInput').value.trim();
        
        if (!code || code.length !== 6 || !/^\d+$/.test(code)) {
            showError('Please enter a valid 6-digit code');
            return;
        }
        if (!zipcode || zipcode.length !== 5 || !/^\d+$/.test(zipcode)) {  // ADD THIS
            showError('Please enter a valid 5-digit zip code');
            return;
        }
        
        setLoading(true, 'Verifying code...');
        hideMessages();

        try {
            const response = await fetch('/api/login/verify', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ 
                    email: userEmail,
                    code: code,
                    zipcode: zipcode  
                })
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.error || 'Invalid code');
            }

            // Success - redirect to main app
            if (data.redirect) {
                window.location.href = data.redirect;
            } else {
                window.location.href = '/';
            }

        } catch (error) {
            console.error('Error verifying code:', error);
            showError(error.message || 'Invalid code. Please try again.');
            codeInput.value = '';
            codeInput.focus();
        } finally {
            setLoading(false);
        }
    });

    // Back to email step
    backToEmailBtn.addEventListener('click', function() {
        codeStep.style.display = 'none';
        emailStep.style.display = 'block';
        codeInput.value = '';
        hideMessages();
        emailInput.focus();
    });

    // Auto-format code input (numbers only, max 6 digits)
    codeInput.addEventListener('input', function(e) {
        let value = e.target.value.replace(/\D/g, ''); // Remove non-digits
        if (value.length > 6) {
            value = value.substring(0, 6);
        }
        e.target.value = value;
    });

    // Auto-submit when 6 digits are entered
    codeInput.addEventListener('input', function(e) {
        if (e.target.value.length === 6) {
            // Small delay to allow user to see the complete code
            setTimeout(() => {
                if (e.target.value.length === 6) {
                    codeForm.dispatchEvent(new Event('submit'));
                }
            }, 300);
        }
    });

    // Helper functions
    function showError(message) {
        errorMessage.textContent = message;
        errorMessage.style.display = 'block';
        successMessage.style.display = 'none';
    }

    function showSuccess(message) {
        successMessage.textContent = message;
        successMessage.style.display = 'block';
        errorMessage.style.display = 'none';
    }

    function hideMessages() {
        errorMessage.style.display = 'none';
        successMessage.style.display = 'none';
    }

    function setLoading(loading, text = 'Processing...') {
        loadingText.textContent = text;
        loadingSpinner.style.display = loading ? 'block' : 'none';
        sendCodeBtn.disabled = loading;
        verifyCodeBtn.disabled = loading;
        emailInput.disabled = loading;
        codeInput.disabled = loading;
    }

    // Check if already authenticated
    async function checkAuth() {
        try {
            const response = await fetch('/api/auth/check');
            const data = await response.json();
            
            if (data.authenticated) {
                window.location.href = '/';
            }
        } catch (error) {
            // Ignore errors - user will need to login
        }
    }

    checkAuth();
});


