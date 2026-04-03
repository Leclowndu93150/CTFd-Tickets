(function(){
    if(!window.init || !window.init.userId) return;

    var POLL_INTERVAL = 15000;
    var nonce = window.init.csrfNonce;
    var badge = null;
    var shownIds = {};
    var soundUrls = ["/themes/core/static/sounds/notification.webm", "/themes/core/static/sounds/notification.mp3"];

    function playSound(){
        try {
            var audio = new Audio();
            audio.volume = 0.5;
            for(var i = 0; i < soundUrls.length; i++){
                var source = document.createElement("source");
                source.src = soundUrls[i];
                audio.appendChild(source);
            }
            audio.play().catch(function(){});
        } catch(e){}
    }

    function findTicketsLink(){
        var links = document.querySelectorAll(".navbar a.nav-link, .navbar .nav-link");
        for(var i = 0; i < links.length; i++){
            if(links[i].textContent.trim() === "Tickets"){
                return links[i];
            }
        }
        return null;
    }

    function ensureBadge(){
        if(badge) return badge;
        var link = findTicketsLink();
        if(!link) return null;
        link.style.position = "relative";
        badge = document.createElement("span");
        badge.id = "ticket-unread-badge";
        badge.style.cssText = "display:none;position:absolute;top:2px;right:-6px;"
            + "background:#dc3545;color:#fff;font-size:10px;font-weight:700;"
            + "min-width:18px;height:18px;line-height:18px;text-align:center;"
            + "border-radius:50%;padding:0 4px;";
        link.appendChild(badge);
        return badge;
    }

    function updateBadge(count){
        var b = ensureBadge();
        if(!b) return;
        if(count > 0){
            b.textContent = count > 99 ? "99+" : count;
            b.style.display = "inline-block";
        } else {
            b.style.display = "none";
        }
    }

    function createToast(notif){
        var toast = document.createElement("div");
        toast.style.cssText = "position:fixed;top:20px;right:20px;z-index:99999;min-width:320px;max-width:420px;"
            + "background:#fff;border:1px solid #dee2e6;border-left:4px solid #007bff;border-radius:6px;"
            + "box-shadow:0 8px 24px rgba(0,0,0,.15);padding:14px 18px;cursor:pointer;"
            + "animation:ticketSlideIn .3s ease;font-family:inherit;";

        var title = document.createElement("div");
        title.style.cssText = "font-weight:600;font-size:14px;margin-bottom:4px;color:#212529;";
        title.textContent = notif.title;

        var body = document.createElement("div");
        body.style.cssText = "font-size:13px;color:#6c757d;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;";
        body.textContent = notif.content;

        var close = document.createElement("span");
        close.style.cssText = "position:absolute;top:8px;right:12px;cursor:pointer;color:#aaa;font-size:18px;line-height:1;";
        close.innerHTML = "&times;";
        close.addEventListener("click", function(e){
            e.stopPropagation();
            toast.remove();
        });

        toast.appendChild(close);
        toast.appendChild(title);
        toast.appendChild(body);

        toast.addEventListener("click", function(){
            window.location = "/tickets/" + notif.ticket_id;
        });

        document.body.appendChild(toast);
        setTimeout(function(){ toast.remove(); }, 8000);
    }

    function poll(){
        var xhr = new XMLHttpRequest();
        xhr.open("GET", "/api/tickets/notifications");
        xhr.setRequestHeader("CSRF-Token", nonce);
        xhr.onload = function(){
            if(xhr.status !== 200) return;
            try {
                var resp = JSON.parse(xhr.responseText);
                if(!resp.success) return;

                var notifs = resp.data || [];
                updateBadge(notifs.length);

                var newCount = 0;
                notifs.forEach(function(n){
                    if(!shownIds[n.id]){
                        shownIds[n.id] = true;
                        createToast(n);
                        newCount++;
                    }
                });
                if(newCount > 0) playSound();
            } catch(e){}
        };
        xhr.send();
    }

    function markAllRead(){
        var xhr = new XMLHttpRequest();
        xhr.open("POST", "/api/tickets/notifications/read");
        xhr.setRequestHeader("Content-Type", "application/json");
        xhr.setRequestHeader("CSRF-Token", nonce);
        xhr.onload = function(){ updateBadge(0); };
        xhr.send(JSON.stringify({}));
    }

    var onTicketsPage = /^\/tickets(\/|$)/.test(window.location.pathname);
    if(onTicketsPage){
        markAllRead();
    }

    var link = findTicketsLink();
    if(link){
        link.addEventListener("click", function(){
            markAllRead();
        });
    }

    if(!document.getElementById("ticket-toast-style")){
        var style = document.createElement("style");
        style.id = "ticket-toast-style";
        style.textContent = "@keyframes ticketSlideIn{from{transform:translateX(100%);opacity:0}to{transform:translateX(0);opacity:1}}";
        document.head.appendChild(style);
    }

    setTimeout(poll, 2000);
    setInterval(poll, POLL_INTERVAL);
})();
