const getApiBaseUrl = () => {
    const { protocol, hostname, host } = window.location;

    // Local development
    if (hostname === "127.0.0.1" || hostname === "localhost") {
        return "http://127.0.0.1:8000";
    }

    // Production
    return `${protocol}//${host}`;
};

const getWsUrl = () => {
    const { protocol, hostname, host } = window.location;

    const wsProtocol = protocol === "https:" ? "wss:" : "ws:";

    // Local development
    if (hostname === "127.0.0.1" || hostname === "localhost") {
        return "ws://127.0.0.1:8000/ws";
    }

    // Production
    return `${wsProtocol}//${host}/ws`;
};

window.API_BASE_URL = getApiBaseUrl();
window.WS_URL = getWsUrl();
