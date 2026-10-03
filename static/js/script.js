// Shared beginner-friendly JavaScript for VolunteerHub.

function goBack() {
    if (window.history.length > 1) {
        window.history.back();
    } else {
        window.location.href = "/";
    }
}

async function checkServer() {
    const button = document.getElementById("serverStatus");
    if (!button) return;

    try {
        const response = await fetch("/health", { cache: "no-store" });
        if (!response.ok) throw new Error("Server is unavailable");
        button.className = "server-status is-online";
        button.innerHTML = '<i class="bi bi-circle-fill"></i> Server online';
    } catch (error) {
        button.className = "server-status is-offline";
        button.innerHTML = '<i class="bi bi-circle-fill"></i> Server offline';
    }
}

function showTodayDate() {
    const dateElement = document.getElementById("todayDate");
    if (!dateElement) return;

    dateElement.textContent = new Intl.DateTimeFormat("en-NP", {
        day: "numeric",
        month: "short",
        year: "numeric"
    }).format(new Date());
}

function addDistrictHints() {
    document.querySelectorAll('input[name="location"]').forEach((input) => {
        input.placeholder = "District only, e.g. Kathmandu";
        input.title = "Please enter your district only";

        if (!input.nextElementSibling?.classList.contains("district-hint")) {
            const hint = document.createElement("small");
            hint.className = "district-hint d-block mb-2";
            hint.textContent = "District only — do not enter a street address.";
            input.insertAdjacentElement("afterend", hint);
        }
    });
}

function clearChoices(groupName) {
    document.querySelectorAll(`input[name="${groupName}"]`).forEach((input) => {
        input.checked = false;
    });
}

function enableClearButtons() {
    document.querySelectorAll("[data-clear-group]").forEach((button) => {
        button.addEventListener("click", () => clearChoices(button.dataset.clearGroup));
    });
}

function showFlashPopup() {
    const flashData = document.getElementById("flashMessages");
    if (!flashData || !flashData.textContent) return;

    const messages = JSON.parse(flashData.textContent);
    if (!messages.length) return;

    const [category, message] = messages[0];
    const title = document.getElementById("popupTitle");
    const body = document.getElementById("popupMessage");

    title.textContent = category === "success" ? "Success" :
        category === "danger" ? "Please check your details" : "VolunteerHub message";
    body.textContent = message;

    new bootstrap.Modal(document.getElementById("messagePopup")).show();
}

document.addEventListener("DOMContentLoaded", () => {
    const backButton = document.getElementById("backButton");
    if (backButton) backButton.addEventListener("click", goBack);

    showTodayDate();
    checkServer();
    setInterval(checkServer, 15000);
    addDistrictHints();
    enableClearButtons();
    showFlashPopup();
});
