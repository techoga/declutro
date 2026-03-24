document.addEventListener("DOMContentLoaded", () => {
    const shell = document.querySelector("[data-public-shell]");
    const navPanel = document.querySelector("[data-public-nav-panel]");
    const navBackdrop = document.querySelector("[data-public-nav-backdrop]");
    const navToggles = document.querySelectorAll("[data-public-nav-toggle]");
    const navCloses = document.querySelectorAll("[data-public-nav-close]");
    const navLinks = document.querySelectorAll(".site-nav-panel-links .site-nav-link");

    const setNavOpen = (isOpen) => {
        if (!shell || !navPanel || !navBackdrop) {
            return;
        }

        shell.classList.toggle("is-nav-open", isOpen);
        document.body.classList.toggle("public-nav-open", isOpen);
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
        link.addEventListener("click", () => setNavOpen(false));
    });

    window.addEventListener("resize", () => {
        if (window.innerWidth > 1180) {
            setNavOpen(false);
        }
    });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            setNavOpen(false);
        }
    });
});
