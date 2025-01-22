function changeLightMode() {
    const isDark = localStorage.getItem("lightMode") !== "true";
    localStorage.setItem("lightMode", isDark ? "true" : "false");
    setLightMode();
    
    // Add smooth transition animation
    document.documentElement.style.transition = 'all 0.3s ease';
    setTimeout(() => {
        document.documentElement.style.transition = '';
    }, 300);
}

function setLightMode() {
    document.documentElement.setAttribute('data-theme', 
        localStorage.getItem("lightMode") === "true" ? "light" : "dark"
    );
}

// Initialize theme
if (localStorage.getItem("lightMode") === null) {
    localStorage.setItem("lightMode", "false");
}
setLightMode();
