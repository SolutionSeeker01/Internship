// user-management.js - Platform Administration Controller
'use strict';

document.addEventListener('DOMContentLoaded', async () => {
    const tableBody = document.getElementById('users-table-body');
    const createForm = document.getElementById('create-user-form');
    const notificationBox = document.getElementById('notification-box');
    const btnDashboard = document.getElementById('nav-btn-dashboard');
    const clockEl = document.getElementById('header-clock');

    // 1. Session verification check
    const accessToken = localStorage.getItem('access_token');
    const userStr = localStorage.getItem('user');

    if (!accessToken || !userStr) {
        localStorage.clear();
        window.location.replace('login.html');
        return;
    }

    const currentUser = JSON.parse(userStr);

    // Verify MASTER role permission on load
    if (currentUser.role !== 'MASTER') {
        alert('Forbidden: Master role required');
        window.location.replace('dashboard.html');
        return;
    }

    // 4. Utility function to render notifications
    function showNotification(message, type = 'success') {
        if (!notificationBox) return;
        notificationBox.textContent = message;
        notificationBox.className = `notification-box notification-${type}`;
        notificationBox.style.display = 'block';

        setTimeout(() => {
            notificationBox.style.display = 'none';
        }, 5000);
    }

    let cachedUsersList = [];

    // 5. Fetch all users from API and populate the table
    async function loadUsers() {
        try {
            const response = await fetch(`${window.API_BASE_URL}/users`, {
                method: 'GET',
                headers: {
                    'Authorization': `Bearer ${accessToken}`,
                    'Content-Type': 'application/json'
                }
            });

            if (response.status === 401) {
                localStorage.clear();
                window.location.replace('login.html');
                return;
            }

            if (response.status === 403) {
                window.location.replace('dashboard.html');
                return;
            }

            if (!response.ok) {
                throw new Error('Failed to retrieve user directory');
            }

            cachedUsersList = await response.json();
            applySearchFilter();
        } catch (e) {
            showNotification(e.message, 'error');
        }
    }

    // Search filter execution
    function applySearchFilter() {
        const searchInput = document.getElementById('search-users-input');
        const query = searchInput ? searchInput.value.trim().toLowerCase() : '';
        
        if (!query) {
            renderUsersTable(cachedUsersList);
            return;
        }

        const filtered = cachedUsersList.filter(user => {
            const matchName = user.fullname && user.fullname.toLowerCase().includes(query);
            const matchUsername = user.username && user.username.toLowerCase().includes(query);
            const matchEmail = user.email && user.email.toLowerCase().includes(query);
            return matchName || matchUsername || matchEmail;
        });

        renderUsersTable(filtered);
    }

    // Attach search event listener
    const searchInput = document.getElementById('search-users-input');
    if (searchInput) {
        searchInput.addEventListener('input', applySearchFilter);
    }

    // 6. Render table rows
    function renderUsersTable(users) {
        if (!tableBody) return;
        tableBody.innerHTML = '';

        users.forEach(user => {
            const tr = document.createElement('tr');

            // Name
            const tdName = document.createElement('td');
            tdName.textContent = user.fullname || '-';
            tr.appendChild(tdName);

            // Username
            const tdUsername = document.createElement('td');
            tdUsername.textContent = user.username;
            tr.appendChild(tdUsername);

            // Email
            const tdEmail = document.createElement('td');
            tdEmail.textContent = user.email;
            tr.appendChild(tdEmail);

            // Role Badge
            const tdRole = document.createElement('td');
            const badge = document.createElement('span');
            badge.className = `badge badge-${user.role.toLowerCase()}`;
            badge.textContent = user.role;
            tdRole.appendChild(badge);
            tr.appendChild(tdRole);

            // Status indicator
            const tdStatus = document.createElement('td');
            const statusSpan = document.createElement('span');
            statusSpan.className = user.is_active ? 'status-active' : 'status-inactive';
            statusSpan.textContent = user.is_active ? 'Active' : 'Disabled';
            tdStatus.appendChild(statusSpan);
            tr.appendChild(tdStatus);

            // Action operations
            const tdActions = document.createElement('td');
            tdActions.className = 'text-right';
            tdActions.style.display = 'flex';
            tdActions.style.gap = '8px';
            tdActions.style.justifyContent = 'flex-end';

            // Edit User Button
            const btnEdit = document.createElement('button');
            btnEdit.className = 'btn-action btn-enable';
            btnEdit.style.backgroundColor = '#eff6ff';
            btnEdit.style.color = '#1e40af';
            btnEdit.style.borderColor = '#bfdbfe';
            btnEdit.textContent = 'Edit';
            btnEdit.addEventListener('click', () => handleEditUser(user));
            tdActions.appendChild(btnEdit);

            // Reset Password Button
            const btnReset = document.createElement('button');
            btnReset.className = 'btn-action btn-enable';
            btnReset.style.backgroundColor = '#fafafa';
            btnReset.style.color = '#475569';
            btnReset.style.borderColor = '#e2e8f0';
            btnReset.textContent = 'Reset PW';
            btnReset.addEventListener('click', () => handleResetPassword(user));
            tdActions.appendChild(btnReset);

            const btn = document.createElement('button');
            btn.className = `btn-action ${user.is_active ? 'btn-disable' : 'btn-enable'}`;
            btn.textContent = user.is_active ? 'Disable' : 'Enable';

            // Prevent self-disable
            if (user.id === currentUser.id) {
                btn.disabled = true;
            } else {
                btn.addEventListener('click', () => {
                    const message = user.is_active 
                        ? 'Are you sure you want to disable this user?\n\nThe user will no longer be able to log in.'
                        : 'Are you sure you want to enable this user?';
                    
                    if (window.confirm(message)) {
                        toggleUserStatus(user.id, !user.is_active);
                    }
                });
            }

            tdActions.appendChild(btn);
            tr.appendChild(tdActions);

            tableBody.appendChild(tr);
        });
    }

    // 7. Update User Status call
    async function toggleUserStatus(userId, isActive) {
        try {
            const response = await fetch(`${window.API_BASE_URL}/users/${userId}/status`, {
                method: 'PATCH',
                headers: {
                    'Authorization': `Bearer ${accessToken}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ is_active: isActive })
            });

            if (response.status === 401) {
                localStorage.clear();
                window.location.replace('login.html');
                return;
            }

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || 'Failed to update user status');
            }

            showNotification(`User status updated successfully`, 'success');
            loadUsers();
        } catch (e) {
            showNotification(e.message, 'error');
        }
    }

    // Track active editing and password reset states
    let currentEditingUserId = null;
    let currentResetUserId = null;

    // 8. Form submit handler (Create / Update / Reset Password User)
    if (createForm) {
        createForm.addEventListener('submit', async (event) => {
            event.preventDefault();

            const fullname = document.getElementById('fullname').value.trim();
            const username = document.getElementById('username').value.trim();
            const email = document.getElementById('email').value.trim();
            const role = document.getElementById('role').value;

            // Password reset mode check
            if (currentResetUserId !== null) {
                const password = document.getElementById('password').value;
                const confirmPassword = document.getElementById('confirm-password').value;

                if (password !== confirmPassword) {
                    showNotification('Passwords do not match.', 'error');
                    return;
                }

                // Password Complexity check: min 8 chars, 1 uppercase, 1 lowercase, 1 number, 1 special char
                const hasUppercase = /[A-Z]/.test(password);
                const hasLowercase = /[a-z]/.test(password);
                const hasNumber = /\d/.test(password);
                const hasSpecial = /[!@#$%^&*(),.?":{}|<>]/.test(password);

                if (password.length < 8 || !hasUppercase || !hasLowercase || !hasNumber || !hasSpecial) {
                    showNotification(
                        'Password must be at least 8 characters long and contain at least one uppercase letter, one lowercase letter, one numeric digit, and one special character.',
                        'error'
                    );
                    return;
                }

                if (window.confirm("Are you sure you want to reset this user's password?")) {
                    try {
                        const response = await fetch(`${window.API_BASE_URL}/users/${currentResetUserId}/password`, {
                            method: 'PATCH',
                            headers: {
                                'Authorization': `Bearer ${accessToken}`,
                                'Content-Type': 'application/json'
                            },
                            body: JSON.stringify({
                                password,
                                confirm_password: confirmPassword
                            })
                        });

                        if (response.status === 401) {
                            localStorage.clear();
                            window.location.replace('login.html');
                            return;
                        }

                        if (!response.ok) {
                            const errorData = await response.json();
                            throw new Error(errorData.detail || 'Failed to reset password');
                        }

                        showNotification('Password reset successful', 'success');
                        
                        // Check if MASTER reset their own password
                        if (currentResetUserId === currentUser.id) {
                            alert('Your password has been changed. Please login again.');
                            localStorage.removeItem('access_token');
                            localStorage.removeItem('user');
                            window.location.replace('login.html');
                            return;
                        }

                        exitEditMode();
                        loadUsers();
                    } catch (e) {
                        showNotification(e.message, 'error');
                    }
                }
                return;
            }

            // Mode check
            if (currentEditingUserId !== null) {
                // Edit Mode Update
                if (window.confirm("Are you sure you want to update this user?")) {
                    try {
                        const response = await fetch(`${window.API_BASE_URL}/users/${currentEditingUserId}`, {
                            method: 'PATCH',
                            headers: {
                                'Authorization': `Bearer ${accessToken}`,
                                'Content-Type': 'application/json'
                            },
                            body: JSON.stringify({
                                fullname,
                                email,
                                role
                            })
                        });

                        if (response.status === 401) {
                            localStorage.clear();
                            window.location.replace('login.html');
                            return;
                        }

                        if (!response.ok) {
                            const errorData = await response.json();
                            throw new Error(errorData.detail || 'Failed to update user details');
                        }

                        showNotification('User updated successfully', 'success');
                        exitEditMode();
                        loadUsers();
                    } catch (e) {
                        showNotification(e.message, 'error');
                    }
                }
                return;
            }

            // Create Mode Submission
            const password = document.getElementById('password').value;
            const confirmPassword = document.getElementById('confirm-password').value;

            // Password Confirmation match check
            if (password !== confirmPassword) {
                showNotification('Passwords do not match.', 'error');
                return;
            }

            // Password Complexity check: min 8 chars, 1 uppercase, 1 lowercase, 1 number, 1 special char
            const hasUppercase = /[A-Z]/.test(password);
            const hasLowercase = /[a-z]/.test(password);
            const hasNumber = /\d/.test(password);
            const hasSpecial = /[!@#$%^&*(),.?":{}|<>]/.test(password);

            if (password.length < 8 || !hasUppercase || !hasLowercase || !hasNumber || !hasSpecial) {
                showNotification(
                    'Password must be at least 8 characters long and contain at least one uppercase letter, one lowercase letter, one numeric digit, and one special character.',
                    'error'
                );
                return;
            }

            try {
                const response = await fetch(`${window.API_BASE_URL}/users`, {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${accessToken}`,
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        fullname,
                        username,
                        email,
                        password,
                        confirm_password: confirmPassword,
                        role
                    })
                });

                if (response.status === 401) {
                    localStorage.clear();
                    window.location.replace('login.html');
                    return;
                }

                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(errorData.detail || 'Failed to create user');
                }

                showNotification('User created successfully', 'success');
                createForm.reset();
                loadUsers();
            } catch (e) {
                showNotification(e.message, 'error');
            }
        });
    }

    // 9. Edit User logic (inline form swap)
    function handleEditUser(user) {
        currentEditingUserId = user.id;

        // Prefill form values
        document.getElementById('fullname').value = user.fullname;
        
        const usernameInput = document.getElementById('username');
        usernameInput.value = user.username;
        usernameInput.disabled = true;

        document.getElementById('email').value = user.email;
        document.getElementById('role').value = user.role;

        // Hide password fields container and disable inputs to prevent form submit blocks
        const passwordContainer = document.getElementById('password-fields-container');
        if (passwordContainer) {
            passwordContainer.style.display = 'none';
            document.getElementById('password').disabled = true;
            document.getElementById('confirm-password').disabled = true;
        }

        // Change card titles and submit text
        const formTitle = document.getElementById('form-title');
        if (formTitle) formTitle.textContent = 'Update User';

        const submitBtn = document.getElementById('btn-create-submit');
        if (submitBtn) submitBtn.textContent = 'Update User';

        // Show cancel button
        const cancelBtn = document.getElementById('btn-cancel-edit');
        if (cancelBtn) cancelBtn.style.display = 'inline-block';
    }

    function exitEditMode() {
        currentEditingUserId = null;
        currentResetUserId = null;
        if (createForm) createForm.reset();

        // Restore form elements visibility and enabled state
        const fullnameGroup = document.getElementById('fullname-field-group');
        if (fullnameGroup) fullnameGroup.style.display = 'flex';
        document.getElementById('fullname').disabled = false;

        const usernameInput = document.getElementById('username');
        if (usernameInput) {
            usernameInput.disabled = false;
        }
        const usernameGroup = document.getElementById('username-field-group');
        if (usernameGroup) usernameGroup.style.display = 'flex';

        const emailGroup = document.getElementById('email-field-group');
        if (emailGroup) emailGroup.style.display = 'flex';
        document.getElementById('email').disabled = false;

        const roleGroup = document.getElementById('role-field-group');
        if (roleGroup) roleGroup.style.display = 'flex';
        document.getElementById('role').disabled = false;

        // Show password fields container
        const passwordContainer = document.getElementById('password-fields-container');
        if (passwordContainer) {
            passwordContainer.style.display = 'block';
            document.getElementById('password').disabled = false;
            document.getElementById('confirm-password').disabled = false;

            // Restore placeholder texts
            document.getElementById('password').placeholder = 'Enter Password';
            document.getElementById('confirm-password').placeholder = 'Confirm Password';
            document.getElementById('lbl-password').textContent = 'Password';
        }

        // Restore titles
        const formTitle = document.getElementById('form-title');
        if (formTitle) formTitle.textContent = 'Create User';

        const submitBtn = document.getElementById('btn-create-submit');
        if (submitBtn) submitBtn.textContent = 'Create User';

        // Hide cancel button
        const cancelBtn = document.getElementById('btn-cancel-edit');
        if (cancelBtn) cancelBtn.style.display = 'none';
    }

    // Attach cancel click listener programmatically
    const cancelBtn = document.getElementById('btn-cancel-edit');
    if (cancelBtn) {
        cancelBtn.addEventListener('click', exitEditMode);
    }

    // 10. Reset Password logic (inline form swap)
    function handleResetPassword(user) {
        currentResetUserId = user.id;
        currentEditingUserId = null; // Clear edit pointer

        if (createForm) createForm.reset();

        // Hide fields unrelated to password resets and disable them to avoid submit validation blocks
        const fullnameGroup = document.getElementById('fullname-field-group');
        if (fullnameGroup) fullnameGroup.style.display = 'none';
        document.getElementById('fullname').disabled = true;

        const emailGroup = document.getElementById('email-field-group');
        if (emailGroup) emailGroup.style.display = 'none';
        document.getElementById('email').disabled = true;

        const roleGroup = document.getElementById('role-field-group');
        if (roleGroup) roleGroup.style.display = 'none';
        document.getElementById('role').disabled = true;

        // Show username field as readonly
        const usernameInput = document.getElementById('username');
        if (usernameInput) {
            usernameInput.value = user.username;
            usernameInput.disabled = true;
        }
        const usernameGroup = document.getElementById('username-field-group');
        if (usernameGroup) usernameGroup.style.display = 'flex';

        // Show password fields
        const passwordContainer = document.getElementById('password-fields-container');
        if (passwordContainer) {
            passwordContainer.style.display = 'block';
            document.getElementById('password').disabled = false;
            document.getElementById('confirm-password').disabled = false;

            // Customize labels
            document.getElementById('password').placeholder = 'Enter New Password';
            document.getElementById('confirm-password').placeholder = 'Confirm New Password';
            document.getElementById('lbl-password').textContent = 'New Password';
        }

        // Change card titles and submit text
        const formTitle = document.getElementById('form-title');
        if (formTitle) formTitle.textContent = 'Reset Password';

        const submitBtn = document.getElementById('btn-create-submit');
        if (submitBtn) submitBtn.textContent = 'Reset Password';

        // Show cancel button
        const cancelBtn = document.getElementById('btn-cancel-edit');
        if (cancelBtn) cancelBtn.style.display = 'inline-block';
    }

    // Password Show/Hide Toggle Implementation
    const btnTogglePassword = document.getElementById('btn-toggle-password');
    const inputPassword = document.getElementById('password');
    if (btnTogglePassword && inputPassword) {
        btnTogglePassword.addEventListener('click', () => {
            const isPassword = inputPassword.type === 'password';
            inputPassword.type = isPassword ? 'text' : 'password';
            btnTogglePassword.textContent = isPassword ? '🙈' : '👁️';
        });
    }

    const btnToggleConfirmPassword = document.getElementById('btn-toggle-confirm-password');
    const inputConfirmPassword = document.getElementById('confirm-password');
    if (btnToggleConfirmPassword && inputConfirmPassword) {
        btnToggleConfirmPassword.addEventListener('click', () => {
            const isPassword = inputConfirmPassword.type === 'password';
            inputConfirmPassword.type = isPassword ? 'text' : 'password';
            btnToggleConfirmPassword.textContent = isPassword ? '🙈' : '👁️';
        });
    }

    // Initial table load
    loadUsers();
});
