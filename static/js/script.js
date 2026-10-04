// Shared beginner-friendly JavaScript for VolunteerHub.

function goBack() {
    if (window.history.length > 1) {
        window.history.back();
    } else {
        window.location.href = "/";
    }
}

function setServerStatus(button, online) {
    button.className = `server-status ${online ? "is-online" : "is-offline"}`;
    button.title = `Database: ${online ? "Online" : "Offline"}`;
}

async function checkServer() {
    const button = document.getElementById("serverStatus");
    if (!button) return;

    try {
        const response = await fetch("/health", { cache: "no-store" });
        if (!response.ok) throw new Error("Database connection unavailable");
        const data = await response.json();
        if (data.status !== "online") throw new Error("MySQL offline");
        setServerStatus(button, true);
    } catch (error) {
        setServerStatus(button, false);
    }
}



function showCurrentDateTime() {
    const dateElement = document.getElementById("todayDate");
    if (!dateElement) return;

    dateElement.textContent = new Intl.DateTimeFormat("en-NP", {
        day: "numeric",
        month: "short",
        year: "numeric",
        hour: "numeric",
        minute: "2-digit",
        second: "2-digit"
    }).format(new Date());
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

function checkTaskImageSize() {
    const imageInput = document.querySelector("[data-fixed-image]");
    if (!imageInput) return;

    imageInput.addEventListener("change", () => {
        const file = imageInput.files[0];
        if (!file) return;

        const image = new Image();
        image.onload = () => {
            if (image.width !== 1200 || image.height !== 675) {
                alert("Task images must be exactly 1200 × 675 pixels. Please choose another image.");
                imageInput.value = "";
            }
            URL.revokeObjectURL(image.src);
        };
        image.src = URL.createObjectURL(file);
    });
}

function addCheckbox(list, groupName, prefix, name) {
    const id = `${prefix}-${name.replace(/[^a-z0-9]/gi, "-").toLowerCase()}`;
    if (document.getElementById(id)) return;

    const item = document.createElement("div");
    item.className = "form-check";
    const checkbox = document.createElement("input");
    checkbox.className = "form-check-input";
    checkbox.type = "checkbox";
    checkbox.name = groupName;
    checkbox.value = name;
    checkbox.id = id;
    checkbox.checked = true;

    const label = document.createElement("label");
    label.className = "form-check-label";
    label.htmlFor = id;
    label.textContent = name;
    item.append(checkbox, label);
    list.appendChild(item);
}

// Skills and interests are saved in the same way, so one function handles both.
function enableCatalogButton(config) {
    const input = document.getElementById(config.inputId);
    const button = document.querySelector(config.buttonSelector);
    const list = document.getElementById(config.listId);
    const message = document.getElementById(config.messageId);
    if (!input || !button || !list || !message) return;

    button.addEventListener("click", async () => {
        const name = input.value.trim();
        if (!name) return showCatalogMessage(message, config.emptyMessage, false);

        button.disabled = true;
        try {
            const response = await fetch(config.url, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name })
            });
            const result = await response.json();
            if (!response.ok) {
                return showCatalogMessage(message, result.message || config.errorMessage, false);
            }
            addCheckbox(list, config.groupName, config.prefix, result.name);
            input.value = "";
            showCatalogMessage(message, result.message, true);
        } catch (error) {
            showCatalogMessage(message, config.errorMessage, false);
        } finally {
            button.disabled = false;
        }
    });
}

function showCatalogMessage(element, text, isSuccess) {
    element.textContent = text;
    element.className = `${isSuccess ? "text-success" : "text-danger"} d-block mb-3`;
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

function checkPasswordMatching() {
    document.querySelectorAll("form").forEach((form) => {
        const pwdInput = form.querySelector('input[name="password"]');
        const confirmInput = form.querySelector('input[name="confirm_password"]');
        if (!pwdInput || !confirmInput) return;

        form.addEventListener("submit", (e) => {
            const pwd = pwdInput.value.trim();
            const confirmPwd = confirmInput.value.trim();
            if (pwd || confirmPwd) {
                if (pwd !== confirmPwd) {
                    e.preventDefault();
                    alert("Passwords do not match! Please make sure both password fields are identical.");
                    confirmInput.focus();
                }
            }
        });
    });
}

document.addEventListener("DOMContentLoaded", () => {
    const backButton = document.getElementById("backButton");
    if (backButton) backButton.addEventListener("click", goBack);

    showCurrentDateTime();
    setInterval(showCurrentDateTime, 1000);
    checkServer();
    setInterval(checkServer, 15000);
    enableClearButtons();
    checkTaskImageSize();
    enableCatalogButton({
        inputId: "newSkill", buttonSelector: "[data-add-skill]", listId: "requiredSkills",
        messageId: "skillMessage", url: "/catalog/skills", groupName: "required_skills",
        prefix: "skill", emptyMessage: "Type a skill name first.",
        errorMessage: "The skill could not be saved."
    });
    enableCatalogButton({
        inputId: "newInterest", buttonSelector: "[data-add-interest]", listId: "taskInterests",
        messageId: "interestMessage", url: "/catalog/interests", groupName: "interests",
        prefix: "interest", emptyMessage: "Type a hobby or interest first.",
        errorMessage: "The interest could not be saved."
    });
    checkPasswordMatching();
    showFlashPopup();
});
