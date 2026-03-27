import { createContext, useContext, useState, useEffect } from 'react';

// API URL - same as in App.jsx
const API_URL = 'http://localhost:8000';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
    const [user, setUser] = useState(null);
    const [isLoading, setIsLoading] = useState(true);

    // Check for existing session on mount
    useEffect(() => {
        const storedUser = localStorage.getItem('company_voice_user');
        if (storedUser) {
            try {
                const parsedUser = JSON.parse(storedUser);
                setUser(parsedUser);
            } catch (e) {
                localStorage.removeItem('company_voice_user');
            }
        }
        setIsLoading(false);
    }, []);

    const login = async (username, password) => {
        try {
            const response = await fetch(`${API_URL}/api/auth/login`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password })
            });

            const data = await response.json();

            if (data.success && data.user) {
                const userData = {
                    id: data.user.id,
                    username: data.user.username,
                    role: data.user.role,
                    displayName: data.user.display_name || data.user.username,
                    email: data.user.email,
                    organizationId: data.user.organization_id,  // NEW: For multi-tenant filtering
                    loginTime: new Date().toISOString()
                };

                setUser(userData);
                localStorage.setItem('company_voice_user', JSON.stringify(userData));
                return { success: true };
            } else {
                return { success: false, error: data.message || 'Invalid credentials' };
            }
        } catch (error) {
            console.error('Login error:', error);
            // Fallback to hardcoded credentials if API is not available
            return fallbackLogin(username, password);
        }
    };

    // Fallback login for when API is not available (development/offline mode)
    const fallbackLogin = (username, password) => {
        const FALLBACK_USERS = {
            'Agentx': {
                password: 'Admin@123',
                role: 'admin',
                displayName: 'AgentX Admin'
            }
        };

        const userConfig = FALLBACK_USERS[username];

        if (!userConfig) {
            return { success: false, error: 'Invalid username' };
        }

        if (userConfig.password !== password) {
            return { success: false, error: 'Invalid password' };
        }

        const userData = {
            username,
            role: userConfig.role,
            displayName: userConfig.displayName,
            loginTime: new Date().toISOString()
        };

        setUser(userData);
        localStorage.setItem('company_voice_user', JSON.stringify(userData));
        return { success: true };
    };

    const logout = async () => {
        try {
            await fetch(`${API_URL}/api/auth/logout`, { method: 'POST' });
        } catch (error) {
            console.error('Logout API error:', error);
        }
        setUser(null);
        localStorage.removeItem('company_voice_user');
    };

    const isAdmin = () => user?.role === 'admin';
    const isClient = () => user?.role === 'client';

    const value = {
        user,
        isLoading,
        isAuthenticated: !!user,
        login,
        logout,
        isAdmin,
        isClient
    };

    return (
        <AuthContext.Provider value={value}>
            {children}
        </AuthContext.Provider>
    );
}

export function useAuth() {
    const context = useContext(AuthContext);
    if (!context) {
        throw new Error('useAuth must be used within an AuthProvider');
    }
    return context;
}
