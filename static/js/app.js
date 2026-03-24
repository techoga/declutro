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

    const galleryStageImage = document.querySelector("[data-gallery-stage-image]");
    const galleryStageVideo = document.querySelector("[data-gallery-stage-video]");
    const galleryLightbox = document.getElementById("gallery-lightbox");
    const galleryLightboxImage = document.querySelector("[data-gallery-lightbox-image]");
    const galleryLightboxVideo = document.querySelector("[data-gallery-lightbox-video]");
    const galleryLightboxOpen = document.querySelector("[data-gallery-lightbox-open]");
    const galleryThumbs = Array.from(document.querySelectorAll("[data-gallery-thumb]"));
    const galleryOpenTriggers = Array.from(document.querySelectorAll("[data-gallery-open-trigger]"));

    if (galleryThumbs.length && (galleryStageImage || galleryStageVideo)) {
        const mediaByIndex = new Map();
        let activeIndex = "0";

        const setStageMedia = (imageElement, videoElement, media) => {
            if (!imageElement && !videoElement) {
                return;
            }

            if ((media.type || "image") === "video" && videoElement) {
                videoElement.hidden = false;
                videoElement.poster = media.poster || "";
                videoElement.innerHTML = "";
                const source = document.createElement("source");
                source.src = media.src || "";
                videoElement.appendChild(source);
                videoElement.load();
                if (imageElement) {
                    imageElement.hidden = true;
                }
                return;
            }

            if (imageElement) {
                imageElement.src = media.src || "";
                imageElement.alt = media.label || imageElement.alt || "";
                imageElement.hidden = false;
            }
            if (videoElement) {
                videoElement.pause();
                videoElement.hidden = true;
                videoElement.innerHTML = "";
            }
        };

        const syncActiveThumbs = () => {
            galleryThumbs.forEach((thumb) => {
                thumb.classList.toggle("is-active", (thumb.dataset.mediaIndex || "0") === activeIndex);
            });
        };

        const setActiveMedia = (index) => {
            const media = mediaByIndex.get(index);
            if (!media) {
                return;
            }
            activeIndex = index;
            setStageMedia(galleryStageImage, galleryStageVideo, media);
            setStageMedia(galleryLightboxImage, galleryLightboxVideo, media);
            syncActiveThumbs();
        };

        galleryThumbs.forEach((thumb) => {
            const mediaIndex = thumb.dataset.mediaIndex || "0";
            if (!mediaByIndex.has(mediaIndex)) {
                mediaByIndex.set(mediaIndex, {
                    type: thumb.dataset.mediaType || "image",
                    src: thumb.dataset.mediaSrc || "",
                    poster: thumb.dataset.mediaPoster || "",
                    label: thumb.dataset.mediaLabel || "",
                });
            }

            thumb.addEventListener("click", () => {
                setActiveMedia(mediaIndex);
            });
        });

        setActiveMedia(activeIndex);

        if (galleryLightboxOpen && galleryLightbox) {
            galleryLightboxOpen.addEventListener("click", () => {
                setActiveMedia(activeIndex);
                openModal(galleryLightbox);
            });
        }

        galleryOpenTriggers.forEach((trigger) => {
            if (trigger.matches("[data-gallery-thumb]")) {
                return;
            }
            trigger.addEventListener("click", () => {
                if (!galleryLightbox) {
                    return;
                }
                setActiveMedia(activeIndex);
                openModal(galleryLightbox);
            });
        });
    }
});
