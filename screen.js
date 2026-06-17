// Lyrics Sync — redirect stub.
//
// The old standalone "Lyrics Sync" plugin merged into "Lyrics Karaoke"
// (which now hosts the same align + save endpoints alongside the pitch
// extraction and player ribbon). This stub remains as a soft landing
// for users who still have the old nav entry / bookmarks.
//
// On entry, auto-redirect to the merged plugin. The screen.html shows
// a clear "moved" message + button as a fallback if the auto-redirect
// is blocked (e.g. another plugin's showScreen wrapper interferes).
(function () {
    'use strict';
    if (typeof window === 'undefined') return;

    const TARGET = 'plugin-lyrics_karaoke';

    function ensureRedirect(name) {
        if (name !== 'plugin-lyrics_sync') return;
        // Defer so we don't fight whichever showScreen wrapper just
        // brought us here. After the current call settles, re-route to
        // the merged plugin's screen.
        setTimeout(() => {
            // Only redirect if the merged plugin's screen actually
            // exists — otherwise we'd land on a blank screen and the
            // user would have no signal.
            if (document.getElementById(TARGET)) {
                if (typeof window.showScreen === 'function') {
                    window.showScreen(TARGET);
                }
            }
        }, 0);
    }

    function init() {
        const orig = window.showScreen;
        if (typeof orig !== 'function') return;
        window.showScreen = function (name) {
            const ret = orig.apply(this, arguments);
            ensureRedirect(name);
            return ret;
        };
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
