/* =============================================================
   common.js  –  Shared frontend layouts controllers (Clock, Auth, etc)
   ============================================================= */

'use strict';

console.info("[Common] Module loaded.");

/**
 * Handle user logout logic.
 */
function handleLogout() {
    if (window.confirm("Are you sure you want to logout?")) {
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
        const logoutIcon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path><polyline points="16 17 21 12 16 7"></polyline><line x1="21" y1="12" x2="9" y2="12"></line></svg>`;

        // Build navigation buttons
        addNavItem("nav-btn-dashboard", "Dashboard", dashboardIcon, (pageName === "dashboard.html" || pageName === ""));
        addNavItem("nav-btn-instruments", "Instrument Manager", instrumentsIcon, (pageName === "instrument-manager.html"));
        addNavItem("nav-btn-watchlists", "Watchlists", watchlistsIcon, (pageName === "watchlists.html"));
        addNavItem("nav-btn-users", "User Management", usersIcon, (pageName === "user-management.html"));

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

        // Wire click handlers for standard sidebar navigation buttons (scoped to sidebar to avoid picking up duplicate IDs in static HTML headers)
        const btnDashboard = sidebar.querySelector("#nav-btn-dashboard");
        const btnInstruments = sidebar.querySelector("#nav-btn-instruments");
        const btnWatchlists = sidebar.querySelector("#nav-btn-watchlists");
        const btnUsers = sidebar.querySelector("#nav-btn-users");
        const btnLogout = sidebar.querySelector("#nav-btn-logout");

        if (btnDashboard) {
            btnDashboard.addEventListener("click", () => {
                window.location.replace("dashboard.html");
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
        if (btnUsers) {
            btnUsers.addEventListener("click", () => {
                window.location.replace("user-management.html");
            });
        }
        if (btnLogout) {
            btnLogout.addEventListener("click", handleLogout);
        }

        // Check role permission status for User Management visibility
        const userStr = localStorage.getItem("user");
        if (userStr) {
            try {
                const userObj = JSON.parse(userStr);
                if (userObj && userObj.role === "MASTER" && btnUsers) {
                    btnUsers.style.display = "flex";
                } else if (btnUsers) {
                    btnUsers.parentNode.style.display = "none"; // Hide list item completely
                }
            } catch (e) {
                console.error("Failed to parse user details:", e);
            }
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
