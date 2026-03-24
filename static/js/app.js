document.addEventListener("DOMContentLoaded", () => {
    const openModal = (modal) => {
        if (!modal) {
            return;
        }
        modal.hidden = false;
        modal.classList.add("is-open");
    };

    const closeModal = (modal) => {
        if (!modal) {
            return;
        }
        modal.hidden = true;
        modal.classList.remove("is-open");
    };

    document.querySelectorAll("[data-loading-form]").forEach((form) => {
        form.addEventListener("submit", () => {
            const button = form.querySelector("[data-submit-button]");
            if (!button) {
                return;
            }
            button.disabled = true;
            button.classList.add("is-loading");
            const label = button.querySelector(".button-label");
            if (label) {
                label.dataset.originalText = label.textContent;
                label.textContent = "Please wait...";
            }
        });
    });

    document.querySelectorAll("[data-dropdown]").forEach((dropdown) => {
        const trigger = dropdown.querySelector("[data-dropdown-trigger]");
        const menu = dropdown.querySelector("[data-dropdown-menu]");
        if (!trigger || !menu) {
            return;
        }

        trigger.addEventListener("click", (event) => {
            event.stopPropagation();
            const isOpen = !menu.hasAttribute("hidden");
            document.querySelectorAll("[data-dropdown-menu]").forEach((item) => {
                item.setAttribute("hidden", "");
            });
            document.querySelectorAll("[data-dropdown-trigger]").forEach((item) => {
                item.setAttribute("aria-expanded", "false");
            });

            if (!isOpen) {
                menu.removeAttribute("hidden");
                trigger.setAttribute("aria-expanded", "true");
            }
        });
    });

    document.addEventListener("click", () => {
        document.querySelectorAll("[data-dropdown-menu]").forEach((item) => {
            item.setAttribute("hidden", "");
        });
        document.querySelectorAll("[data-dropdown-trigger]").forEach((item) => {
            item.setAttribute("aria-expanded", "false");
        });
    });

    document.querySelectorAll("[data-modal-open]").forEach((trigger) => {
        trigger.addEventListener("click", () => {
            const modal = document.getElementById(trigger.dataset.modalOpen);
            openModal(modal);
        });
    });

    document.querySelectorAll("[data-modal-close]").forEach((trigger) => {
        trigger.addEventListener("click", () => {
            closeModal(trigger.closest(".modal-backdrop"));
        });
    });

    document.querySelectorAll(".modal-backdrop").forEach((modal) => {
        modal.addEventListener("click", (event) => {
            if (event.target === modal) {
                closeModal(modal);
            }
        });
    });

    document.addEventListener("keydown", (event) => {
        if (event.key !== "Escape") {
            return;
        }
        document.querySelectorAll(".modal-backdrop.is-open").forEach((modal) => {
            closeModal(modal);
        });
    });

    const galleryStage = document.querySelector("[data-gallery-stage]");
    document.querySelectorAll("[data-gallery-thumb]").forEach((thumb) => {
        thumb.addEventListener("click", () => {
            if (!galleryStage) {
                return;
            }
            galleryStage.src = thumb.dataset.imageSrc;
            document.querySelectorAll("[data-gallery-thumb]").forEach((item) => {
                item.classList.remove("is-active");
            });
            thumb.classList.add("is-active");
        });
    });
});
