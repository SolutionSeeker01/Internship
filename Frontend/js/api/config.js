const getApiBaseUrl = () => {
    const { protocol, hostname, host, port } = window.location;

    // Check if local development (localhost, loopback, private IP ranges, or dev server ports)
    const isLocal = 
        hostname === "127.0.0.1" || 
        hostname === "localhost" || 
        hostname === "" || 
        hostname.startsWith("192.168.") || 
        hostname.startsWith("10.") || 
        hostname.startsWith("172.") || 
        (port && port !== "8000" && port !== "80" && port !== "443");

    if (isLocal) {
        // Point to the backend on port 8000 using the accessed hostname (handles local IPs)
        const targetHost = hostname || "127.0.0.1";
        return `${protocol === "file:" ? "http:" : protocol}//${targetHost}:8000`;
    }

    // Production
    return `${protocol}//${host}`;
};

const getWsUrl = () => {
    const { protocol, hostname, host, port } = window.location;
    const wsProtocol = protocol === "https:" ? "wss:" : "ws:";

    const isLocal = 
        hostname === "127.0.0.1" || 
        hostname === "localhost" || 
        hostname === "" || 
        hostname.startsWith("192.168.") || 
        hostname.startsWith("10.") || 
        hostname.startsWith("172.") || 
        (port && port !== "8000" && port !== "80" && port !== "443");

    if (isLocal) {
        const targetHost = hostname || "127.0.0.1";
        return `ws://${targetHost}:8000/ws`;
    }

    // Production
    return `${wsProtocol}//${host}/ws`;
};

window.API_BASE_URL = getApiBaseUrl();
window.WS_URL = getWsUrl();
