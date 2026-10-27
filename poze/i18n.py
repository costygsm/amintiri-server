"""Mesajele de eroare în engleză, pentru cine nu cere româna (Accept-Language).
Codul scrie mesajele în română; aici doar le traducem la ieșire, după text."""
from starlette.requests import Request

EN = {
    "Cerere invalidă.": "Invalid request.",
    "Miniatura nu se poate face.": "Can't make a thumbnail.",
    "Nu există nicio versiune publicată.": "No version has been published.",
    "Autentificare necesară.": "Sign-in required.",
    "Bucata depășește 8 MiB sau dimensiunea anunțată.": "The chunk is over 8 MiB or the announced size.",
    "Contul n-are folder personal pe NAS, deci n-am unde pune pozele. În DSM: Control Panel → "
    "User & Group → Advanced → User Home → Enable user home service.":
        "This account has no home folder on the NAS, so there's nowhere to put the photos. In DSM: Control Panel → "
        "User & Group → Advanced → User Home → Enable user home service.",
    "Uploadul nu există.": "This upload doesn't exist.",
    "Poza nu există.": "This photo doesn't exist.",
    "Fișierul a ajuns incomplet. Se trimite din nou.": "The file arrived incomplete. It will be sent again.",
    "Linkul nu mai e valabil.": "This link is no longer valid.",
    "Utilizator sau parolă greșită.": "Wrong user name or password.",
    "Prea multe încercări. Încearcă din nou peste 15 minute.": "Too many attempts. Try again in 15 minutes.",
    "Scrie ce cauți.": "Type what you're looking for.",
    "Tip de fișier neacceptat.": "File type not supported.",
    "Bucata nu continuă de unde a rămas uploadul.": "The chunk doesn't continue where the upload left off.",
    "Nu există.": "Not found.",
    "Contul n-are voie să folosească DSM. În DSM: Control Panel → User & Group → "
    "contul → Applications → DSM: Allow.":
        "This account isn't allowed to use DSM. In DSM: Control Panel → User & Group → "
        "the account → Applications → DSM: Allow.",
    "Cerere respinsă.": "Request refused.",
    "Introdu codul din aplicația de autentificare.": "Enter the code from your authenticator app.",
    "Cod greșit.": "Wrong code.",
    "Albumul nu există.": "This album doesn't exist.",
    "Eroare pe server. Încearcă din nou peste un minut.": "Server error. Try again in a minute.",
}


def wants_english(req: Request) -> bool:
    """Prima limbă cerută; fără antet (curl, aplicații vechi) rămâne româna."""
    header = req.headers.get("accept-language", "").strip()
    return bool(header) and not header.lower().startswith("ro")


def localize(body: dict, req: Request) -> dict:
    if wants_english(req) and body.get("error") in EN:
        return {**body, "error": EN[body["error"]]}
    return body
