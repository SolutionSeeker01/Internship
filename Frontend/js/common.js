/* =============================================================
   common.js  –  Shared frontend layouts controllers (Clock, Auth, etc)
   ============================================================= */

'use strict';

console.info("[Common] Module loaded.");

/**
 * Handle user logout logic.
 */
async function handleLogout() {
    if (window.confirm("Are you sure you want to logout?")) {
        const accessToken = localStorage.getItem('access_token');
        if (accessToken) {
            try {
                await fetch(`${window.API_BASE_URL}/auth/logout`, {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${accessToken}`
                    }
                });
            } catch (e) {
                console.error("Failed to notify backend on logout:", e);
            }
        }
        localStorage.removeItem("access_token");
        localStorage.removeItem("user");
        window.location.replace("login.html");
    }
}

/**
 * High-level layout checks and shared DOM initialization.
 */
document.addEventListener('DOMContentLoaded', () => {
    const path = window.location.pathname;
    const pageName = path.substring(path.lastIndexOf('/') + 1);

    // Skip sidebar rendering on login page
    if (pageName === "login.html") return;

    // --- Dynamic Sidebar Construction ---
    const header = document.querySelector('.app-header');
    const mainEl = document.querySelector('main');
    const footer = document.querySelector('.app-footer');

    if (header && mainEl) {
        // Set dynamic active page title in the top navbar header h1
        const headerTitleEl = header.querySelector('h1');
        if (headerTitleEl) {
                    let activeTitle = "Dashboard"; // Default fallback
            if (pageName === "instrument-manager.html") {
                activeTitle = "Instrument Manager";
            } else if (pageName === "watchlists.html") {
                activeTitle = "Watchlists";
            } else if (pageName === "user-management.html") {
                activeTitle = "User Management";
            } else if (pageName === "signal-monitor.html") {
                activeTitle = "Signal Monitor";
            } else if (pageName === "rejected-signals.html") {
                activeTitle = "Rejected Signals";
            }
            headerTitleEl.textContent = activeTitle;
        }

        // Create Sidebar Menu Toggle button next to logo header title
        const headerLeft = header.querySelector('.header-left');
        if (headerLeft) {
            const toggleButton = document.createElement('button');
            toggleButton.className = 'sidebar-toggle-btn';
            toggleButton.setAttribute('aria-label', 'Toggle Sidebar');
            toggleButton.innerHTML = `
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                    <line x1="3" y1="12" x2="21" y2="12"></line>
                    <line x1="3" y1="6" x2="21" y2="6"></line>
                    <line x1="3" y1="18" x2="21" y2="18"></line>
                </svg>
            `;
            headerLeft.insertBefore(toggleButton, headerLeft.firstChild);
        }

        // Create page wrapper layout structure: .app-wrapper & .main-content
        const wrapper = document.createElement('div');
        wrapper.className = 'app-wrapper';

        // Check toggle preferences state
        const isCollapsed = localStorage.getItem('sidebar_collapsed') === 'true';
        if (isCollapsed) {
            wrapper.classList.add('sidebar-collapsed');
        }

        // Insert wrapper layout in DOM
        header.parentNode.insertBefore(wrapper, header.nextSibling);

        // Construct Sidebar content dynamically
        const sidebar = document.createElement('aside');
        sidebar.className = 'app-sidebar';

        // Sidebar Navigation links menu lists
        const menuList = document.createElement('ul');
        menuList.className = 'sidebar-menu';

        // Helper to add links
        const addNavItem = (id, label, iconSvg, activeCondition) => {
            const li = document.createElement('li');
            const btn = document.createElement('button');
            btn.className = 'sidebar-nav-btn';
            btn.id = id;
            btn.setAttribute('data-tooltip', label);
            btn.innerHTML = `${iconSvg} <span class="nav-label">${label}</span>`;
            
            if (activeCondition) {
                btn.classList.add('active');
            }
            li.appendChild(btn);
            menuList.appendChild(li);
        };

        // Icons SVG strings
        const dashboardIcon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path><polyline points="9 22 9 12 15 12 15 22"></polyline></svg>`;
        const instrumentsIcon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="20" x2="18" y2="10"></line><line x1="12" y1="20" x2="12" y2="4"></line><line x1="6" y1="20" x2="6" y2="14"></line></svg>`;
        const watchlistsIcon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"></path></svg>`;
        const usersIcon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle><path d="M23 21v-2a4 4 0 0 0-3-3.87"></path><path d="M16 3.13a4 4 0 0 1 0 7.75"></path></svg>`;
        const signalMonitorIcon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline></svg>`;
        const rejectedSignalsIcon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>`;
        const logoutIcon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path><polyline points="16 17 21 12 16 7"></polyline><line x1="21" y1="12" x2="9" y2="12"></line></svg>`;

        // Build navigation buttons based on user role
        const userObjStr = localStorage.getItem("user");
        let userObj = null;
        try {
            if (userObjStr) userObj = JSON.parse(userObjStr);
        } catch (e) {
            console.error("Failed to parse user session metadata:", e);
        }

        const isClient = userObj && userObj.role === "CLIENT";

        addNavItem("nav-btn-dashboard", "Dashboard", dashboardIcon, (pageName === "dashboard.html" || pageName === "client-dashboard.html" || pageName === ""));
        
        if (!isClient) {
            addNavItem("nav-btn-instruments",      "Instrument Manager", instrumentsIcon,     (pageName === "instrument-manager.html"));
            addNavItem("nav-btn-watchlists",       "Watchlists",         watchlistsIcon,      (pageName === "watchlists.html"));
            addNavItem("nav-btn-signal-monitor",   "Signal Monitor",     signalMonitorIcon,   (pageName === "signal-monitor.html"));
            addNavItem("nav-btn-rejected-signals", "Rejected Signals",   rejectedSignalsIcon, (pageName === "rejected-signals.html"));
            addNavItem("nav-btn-users",            "User Management",    usersIcon,           (pageName === "user-management.html"));
        }

        sidebar.appendChild(menuList);

        // Sidebar Bottom section containing logout
        const bottomSection = document.createElement('div');
        bottomSection.className = 'sidebar-bottom';
        const logoutBtn = document.createElement('button');
        logoutBtn.className = 'sidebar-nav-btn';
        logoutBtn.id = 'nav-btn-logout';
        logoutBtn.setAttribute('data-tooltip', 'Logout');
        logoutBtn.style.color = '#ef4444'; // Red logout button highlight color
        logoutBtn.innerHTML = `${logoutIcon} <span class="nav-label">Logout</span>`;
        bottomSection.appendChild(logoutBtn);
        sidebar.appendChild(bottomSection);

        // Reposition main elements inside layouts wrapper
        const mainContent = document.createElement('div');
        mainContent.className = 'main-content';

        // Append structure in wrapper
        wrapper.appendChild(sidebar);
        wrapper.appendChild(mainContent);

        // Move main content and footer inside layout container wrapper
        mainContent.appendChild(mainEl);
        if (footer) {
            mainContent.appendChild(footer);
        }

        // Toggle Sidebar click event binding
        const menuToggleBtn = header.querySelector('.sidebar-toggle-btn');
        if (menuToggleBtn) {
            menuToggleBtn.addEventListener('click', () => {
                const collapsed = wrapper.classList.toggle('sidebar-collapsed');
                localStorage.setItem('sidebar_collapsed', collapsed);
                
                // Fire custom window resize event automatically to force chart sizes recalculation
                setTimeout(() => {
                    window.dispatchEvent(new Event('resize'));
                }, 260);
            });
        }

        // Wire click handlers for standard sidebar navigation buttons
        const btnDashboard      = sidebar.querySelector("#nav-btn-dashboard");
        const btnInstruments    = sidebar.querySelector("#nav-btn-instruments");
        const btnWatchlists     = sidebar.querySelector("#nav-btn-watchlists");
        const btnSignalMonitor  = sidebar.querySelector("#nav-btn-signal-monitor");
        const btnRejected       = sidebar.querySelector("#nav-btn-rejected-signals");
        const btnUsers          = sidebar.querySelector("#nav-btn-users");
        const btnLogout         = sidebar.querySelector("#nav-btn-logout");

        if (btnDashboard) {
            btnDashboard.addEventListener("click", () => {
                if (isClient) {
                    window.location.replace("client-dashboard.html");
                } else {
                    window.location.replace("dashboard.html");
                }
            });
        }
        if (btnInstruments) {
            btnInstruments.addEventListener("click", () => {
                window.location.replace("instrument-manager.html");
            });
        }
        if (btnWatchlists) {
            btnWatchlists.addEventListener("click", () => {
                window.location.replace("watchlists.html");
            });
        }
        if (btnSignalMonitor) {
            btnSignalMonitor.addEventListener("click", () => {
                window.location.replace("signal-monitor.html");
            });
        }
        if (btnRejected) {
            btnRejected.addEventListener("click", () => {
                window.location.replace("rejected-signals.html");
            });
        }
        if (btnUsers) {
            btnUsers.addEventListener("click", () => {
                window.location.replace("user-management.html");
            });
        }
        if (btnLogout) {
            btnLogout.addEventListener("click", handleLogout);
        }

        // Create Active Broker Badge dynamically in header
        const headerRight = header.querySelector('.header-right');
        if (headerRight) {
            const brokerBadge = document.createElement('div');
            brokerBadge.id = 'header-active-broker-container';
            brokerBadge.className = 'active-broker-badge';
            brokerBadge.style.display = 'flex';
            brokerBadge.style.alignItems = 'center';
            brokerBadge.style.gap = '6px';
            brokerBadge.style.marginRight = '16px';
            brokerBadge.style.padding = '4px 8px';
            brokerBadge.style.borderRadius = '4px';
            brokerBadge.style.background = '#f4f4f5';
            brokerBadge.style.border = '1px solid #e4e4e7';
            brokerBadge.style.fontSize = '12px';
            brokerBadge.style.fontWeight = '600';
            
            brokerBadge.innerHTML = `
                <span style="color: #71717a; font-weight: 500;">Broker:</span>
                <span id="header-active-broker-name" style="text-transform: uppercase;">Loading...</span>
            `;
            headerRight.insertBefore(brokerBadge, headerRight.firstChild);
        }

        // Fetch fresh user profile details dynamically
        const accessToken = localStorage.getItem("access_token");
        if (accessToken) {
            // Run bootstrap check on operational pages to prevent bypass of broker setup or authentication requirements
            const onboardingPages = [
                "login.html",
                "bootstrap.html",
                "broker-auth.html",
                "broker-connect.html",
                "broker-setup.html",
                "broker-callback.html"
            ];
            const isOperationalPage = !onboardingPages.includes(pageName);

            if (isOperationalPage) {
                fetch(`${window.API_BASE_URL}/auth/bootstrap`, {
                    headers: { 'Authorization': `Bearer ${accessToken}` }
                })
                .then(res => {
                    if (res.status === 401) {
                        handleLogout();
                        return null;
                    }
                    return res.json();
                })
                .then(data => {
                    if (!data) return;
                    if (data.state === 'BROKER_SETUP_REQUIRED') {
                        window.location.replace('broker-setup.html');
                    } else if (data.state === 'BROKER_AUTH_REQUIRED') {
                        window.location.replace('broker-auth.html');
                    }
                })
                .catch(e => console.error("Failed to run bootstrap status check:", e));
            }

            fetch(`${window.API_BASE_URL}/auth/me`, {
                headers: { 'Authorization': `Bearer ${accessToken}` }
            })
            .then(res => {
                if (res.status === 401) {
                    handleLogout();
                    return;
                }
                return res.json();
            })
            .then(userObj => {
                if (userObj) {
                    localStorage.setItem("user", JSON.stringify(userObj));
                    
                    const usernameEl = document.getElementById("header-username");
                    if (usernameEl) usernameEl.textContent = userObj.username;
                    
                    const brokerNameEl = document.getElementById("header-active-broker-name");
                    if (brokerNameEl) {
                        brokerNameEl.textContent = userObj.active_broker;
                        brokerNameEl.style.color = userObj.active_broker === 'ZERODHA' ? '#ea580c' : '#0284c7';
                    }
                    
                    if (userObj.role === "MASTER" && btnUsers) {
                        btnUsers.style.display = "flex";
                    }
                }
            })
            .catch(e => console.error("Failed to load user details:", e));
        }
    }

    // --- Header Clock ---
    const clockEl = document.getElementById("header-clock");
    if (clockEl) {
        const updateClock = () => {
            const now = new Date();
            clockEl.textContent = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true });
        };
        updateClock();
        setInterval(updateClock, 1000);
    }
});
