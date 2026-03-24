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

    const primaryImageInput = document.querySelector("[data-dashboard-primary-upload]");
    const galleryInput = document.querySelector("[data-dashboard-gallery-upload]");
    const videoInput = document.querySelector("[data-dashboard-video-upload]");
    const imagePreview = document.querySelector("[data-dashboard-image-preview]");
    const imagePlaceholder = document.querySelector("[data-dashboard-image-placeholder]");
    const galleryPreviewList = document.querySelector("[data-dashboard-gallery-preview-list]");
    const galleryPreviewEmpty = document.querySelector("[data-dashboard-gallery-preview-empty]");
    const videoPreviewList = document.querySelector("[data-dashboard-video-preview-list]");
    const videoPreviewEmpty = document.querySelector("[data-dashboard-video-preview-empty]");
    const previewUrls = [];
    const existingCoverSrc = imagePreview ? imagePreview.getAttribute("src") || "" : "";
    const initialGalleryMarkup = galleryPreviewList ? galleryPreviewList.innerHTML : "";
    const initialVideoMarkup = videoPreviewList ? videoPreviewList.innerHTML : "";

    const rememberPreviewUrl = (url) => {
        previewUrls.push(url);
        return url;
    };

    const clearPreviewUrls = () => {
        while (previewUrls.length) {
            URL.revokeObjectURL(previewUrls.pop());
        }
    };

    const updateCoverPreview = (file) => {
        if (!imagePreview || !imagePlaceholder) {
            return;
        }

        if (!file) {
            if (existingCoverSrc) {
                imagePreview.src = existingCoverSrc;
                imagePreview.hidden = false;
                imagePlaceholder.hidden = true;
            } else {
                imagePreview.hidden = true;
                imagePreview.removeAttribute("src");
                imagePlaceholder.hidden = false;
            }
            return;
        }

        imagePreview.src = rememberPreviewUrl(URL.createObjectURL(file));
        imagePreview.hidden = false;
        imagePlaceholder.hidden = true;
    };

    const renderMediaPreview = (files, list, empty, type) => {
        if (!list || !empty) {
            return;
        }

        list.innerHTML = "";
        if (!files.length) {
            if ((type === "video" && initialVideoMarkup) || (type !== "video" && initialGalleryMarkup)) {
                list.innerHTML = type === "video" ? initialVideoMarkup : initialGalleryMarkup;
                empty.hidden = true;
            } else {
                empty.hidden = false;
            }
            return;
        }

        files.forEach((file, index) => {
            const item = document.createElement("article");
            item.className = `dashboard-preview-media-card${type === "video" ? " dashboard-preview-media-card-video" : ""}`;

            const label = document.createElement("span");
            label.textContent = file.name || `${type === "video" ? "Video" : "Image"} ${index + 1}`;

            if (type === "video") {
                const video = document.createElement("video");
                video.className = "dashboard-preview-media-video";
                video.src = rememberPreviewUrl(URL.createObjectURL(file));
                video.controls = true;
                video.preload = "metadata";
                item.appendChild(video);
            } else {
                const image = document.createElement("img");
                image.className = "dashboard-preview-media-thumb";
                image.src = rememberPreviewUrl(URL.createObjectURL(file));
                image.alt = label.textContent;
                item.appendChild(image);
            }

            item.appendChild(label);
            list.appendChild(item);
        });

        empty.hidden = true;
    };

    if (imagePreview && imagePlaceholder) {
        const primeFromExistingStage = imagePreview.getAttribute("src");
        if (primeFromExistingStage) {
            imagePreview.hidden = false;
            imagePlaceholder.hidden = true;
        }
    }

    if (primaryImageInput && imagePreview && imagePlaceholder) {
        primaryImageInput.addEventListener("change", () => {
            clearPreviewUrls();
            const file = primaryImageInput.files && primaryImageInput.files[0] ? primaryImageInput.files[0] : null;
            updateCoverPreview(file);

            const galleryFiles = galleryInput && galleryInput.files ? Array.from(galleryInput.files) : [];
            const videoFiles = videoInput && videoInput.files ? Array.from(videoInput.files) : [];
            renderMediaPreview(galleryFiles, galleryPreviewList, galleryPreviewEmpty, "image");
            renderMediaPreview(videoFiles, videoPreviewList, videoPreviewEmpty, "video");
        });
    }

    if (galleryInput) {
        galleryInput.addEventListener("change", () => {
            clearPreviewUrls();
            const coverFile = primaryImageInput && primaryImageInput.files && primaryImageInput.files[0]
                ? primaryImageInput.files[0]
                : null;
            updateCoverPreview(coverFile || (galleryInput.files && galleryInput.files[0] ? galleryInput.files[0] : null));
            renderMediaPreview(Array.from(galleryInput.files || []), galleryPreviewList, galleryPreviewEmpty, "image");
            renderMediaPreview(Array.from((videoInput && videoInput.files) || []), videoPreviewList, videoPreviewEmpty, "video");
        });
    }

    if (videoInput) {
        videoInput.addEventListener("change", () => {
            clearPreviewUrls();
            const coverFile = primaryImageInput && primaryImageInput.files && primaryImageInput.files[0]
                ? primaryImageInput.files[0]
                : galleryInput && galleryInput.files && galleryInput.files[0]
                    ? galleryInput.files[0]
                    : null;
            updateCoverPreview(coverFile);
            renderMediaPreview(Array.from((galleryInput && galleryInput.files) || []), galleryPreviewList, galleryPreviewEmpty, "image");
            renderMediaPreview(Array.from(videoInput.files || []), videoPreviewList, videoPreviewEmpty, "video");
        });
    }
});
