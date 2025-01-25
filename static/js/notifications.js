const notificationSystem = {
    show: function(options) {
        const {
            title,
            message,
            type = 'info',
            duration = 3000,
            storageKey,
            showCheckbox = false
        } = options;

        if (storageKey && localStorage.getItem(storageKey)) {
            return Promise.resolve(false);
        }

        return new Promise((resolve) => {
            const notification = document.createElement('div');
            notification.className = `notification ${type}`;
            
            let html = `
                <div>
                    ${title ? `<div class="notification-title">${title}</div>` : ''}
                    <div class="notification-message">${message}</div>
                    ${showCheckbox ? `
                        <div class="notification-checkbox">
                            <input type="checkbox" id="checkbox-${Date.now()}">
                            <label>Do not show again</label>
                        </div>
                    ` : ''}
                </div>
            `;
            
            notification.innerHTML = html;
            
            const container = document.querySelector('.notification-container');
            container.appendChild(notification);

            if (showCheckbox) {
                const checkbox = notification.querySelector('input[type="checkbox"]');
                checkbox.addEventListener('change', (e) => {
                    if (e.target.checked && storageKey) {
                        localStorage.setItem(storageKey, 'true');
                    }
                });
            }

            setTimeout(() => {
                notification.style.animation = 'slideOut 0.3s ease-out forwards';
                setTimeout(() => {
                    notification.remove();
                    resolve(true);
                }, 300);
            }, duration);
        });
    },
    success: function(title, message, duration) {
        return this.show({ title, message, type: 'success', duration });
    },
    error: function(title, message, duration) {
        return this.show({ title, message, type: 'error', duration });
    },
    info: function(title, message, storageKey) {
        return this.show({
            title,
            message,
            type: 'info',
            duration: 5000,
            storageKey,
            showCheckbox: true
        });
    }
};

const showAlert = async (title, text, storageKey) => {
    await notificationSystem.info(title, text, storageKey);
};
