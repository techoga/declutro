document.addEventListener("DOMContentLoaded", () => {
    const shell = document.querySelector("[data-dashboard-shell]");
    const navPanel = document.querySelector("[data-dashboard-nav-panel]");
    const navBackdrop = document.querySelector("[data-dashboard-nav-backdrop]");
    const navToggles = document.querySelectorAll("[data-dashboard-nav-toggle]");
    const navCloses = document.querySelectorAll("[data-dashboard-nav-close]");
    const navLinks = document.querySelectorAll(".workspace-nav-link");

    const setNavOpen = (isOpen) => {
        if (!shell || !navPanel || !navBackdrop) {
            return;
        }

        shell.classList.toggle("is-nav-open", isOpen);
        document.body.classList.toggle("dashboard-nav-open", isOpen);
        navBackdrop.hidden = !isOpen;
        navToggles.forEach((toggle) => {
            toggle.setAttribute("aria-expanded", String(isOpen));
        });
    };

    navToggles.forEach((toggle) => {
        toggle.addEventListener("click", () => setNavOpen(true));
    });

    navCloses.forEach((toggle) => {
        toggle.addEventListener("click", () => setNavOpen(false));
    });

    if (navBackdrop) {
        navBackdrop.addEventListener("click", () => setNavOpen(false));
    }

    navLinks.forEach((link) => {
        link.addEventListener("click", () => {
            if (window.innerWidth <= 1080) {
                setNavOpen(false);
            }
        });
    });

    window.addEventListener("resize", () => {
        if (window.innerWidth > 1080) {
            setNavOpen(false);
        }
    });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            setNavOpen(false);
        }
    });

    const imageInput = document.querySelector("[data-dashboard-image-input]");
    const imagePreview = document.querySelector("[data-dashboard-image-preview]");
    const imagePlaceholder = document.querySelector("[data-dashboard-image-placeholder]");

    const updatePreview = (value) => {
        if (!imagePreview || !imagePlaceholder) {
            return;
        }

        const trimmedValue = value.trim();
        if (!trimmedValue) {
            imagePreview.hidden = true;
            imagePreview.removeAttribute("src");
            imagePlaceholder.hidden = false;
            return;
        }

        imagePreview.src = trimmedValue;
        imagePreview.hidden = false;
        imagePlaceholder.hidden = true;
    };

    if (imageInput && imagePreview && imagePlaceholder) {
        updatePreview(imageInput.value || "");

        imageInput.addEventListener("input", () => {
            updatePreview(imageInput.value || "");
        });

        imagePreview.addEventListener("error", () => {
            imagePreview.hidden = true;
            imagePlaceholder.hidden = false;
        });
    }
});
