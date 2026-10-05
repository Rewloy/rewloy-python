# Rewloy Python

**Rewloy API'nin resmî Python kütüphanesi.**

> **Durum: önizleme (0.x), PyPI'da yayımlandı. API kararlı; kütüphane arayüzü 1.0'a kadar değişebilir.**

[Rewloy](https://rewloy.com), işletmelerin dijital sadakat kartlarını
müşterinin telefonuna koyar. Kart türleri damga, puan, VIP, cashback, hediye
kartı, kupon ve indirimdir:
- iPhone'da Apple Cüzdan;
- Android'de Rewloy Cüzdan ve Google Cüzdan;
- her yerde web kartı.

Kasada QR okutulur; bakiye, ödül ve kampanyalar kartın kendisinde güncellenir.
Panelde yapılabilen her şey [Rewloy API v1](https://rewloy.com/gelistiriciler)
ile de yapılabilir; bu kütüphane onu Python'dan kullanır. Geliştirici
belgeleri: **https://rewloy.com/gelistiriciler**.

- **Tam tipli.** API'nin her işlemi, `operationId` adının snake_case hâliyle
  bir metottur (`passAction` → `pass_action`). İstek gövdeleri, sorgular ve
  yanıtlar OpenAPI belgesinden
  ([`openapi.json`](https://app.rewloy.com/v1/openapi.json)) üretilen
  `TypedDict` tipleriyle gelir; `mypy --strict` geçer. CI belgeyi her gün okur
  ve değişince yeniden üretir.
- **Bağımlılıksız.** Python 3.9 ve üstü; yalnız standart kütüphane (`urllib`,
  `json`, `hmac`). Bağlantı havuzu ve HTTP/2 isteyen için `httpx` taşıması
  isteğe bağlıdır.
- **Güvenli tekrar.** Geçici hatalarda ölçülü yeniden deneme; satışta, kasa
  işleminde ve kampanyada `Idempotency-Key`.
- **Ötesi:** sayfalama, canlı akış (SSE), webhook imzası doğrulama,
  kullanımdan kalkma uyarıları.

## Kurulum

Python 3.9 ya da üstü gerekir:

```sh
pip install rewloy
```

`httpx` taşıması için: `pip install "rewloy[httpx]"`.

## Başlarken

```python
import os
from rewloy import Rewloy

rewloy = Rewloy(api_key=os.environ["REWLOY_API_KEY"])

kart = rewloy.get_pass("ABCD-EFGH-JKLM")
print(kart["type"], kart["balance"], kart["rewardReady"])
```

Her işlem, adı `operationId`'nin snake_case hâli olan bir metottur
([API referansı](https://rewloy.com/gelistiriciler/api); `OPERATION_IDS` ve
`METHOD_NAMES` ikisini eşler). Argümanlar:
- adresteki parametreler konumsaldır: `get_pass(seri)`;
- `query`: sorgu parametreleri (sözlük);
- `body`: JSON gövde (sözlük);
- `merchant`: `Rewloy-Merchant` başlığı;
- `idempotency_key`: `Idempotency-Key` başlığı (satış, kasa işlemi, kampanya ve mağaza iadesinde zorunlu);
- `timeout` (saniye) ve `max_retries`.

Sorgu ve gövde sözlükleri API'deki adlarıyla yazılır (`programId`,
`kvkkConsent`); anahtarlar çevrilmez. Metot yanıttaki `data`yı döndürür:
- bir `TypedDict` ya da liste; yanıtı olduğu gibi alırsınız, API'nin sonradan
  eklediği bir alan hemen sözlüğünüzdedir;
- sayfalı listelerde `Page` (`sayfa.data`, `sayfa.meta`);
- gövdesiz yanıtta (`204`) `None`;
- dosyada (QR, harita, CSV, `.pkpass`) `bytes`.

Tipler `rewloy.types` altındadır: `IssuePassBody`, `GetPassData`,
`ListCustomersItem`, `ErrorCode`… Çalışma anında yüklenmemeleri için
(`import rewloy` onları yüklemez; yaklaşık 80 ms tutar) yalnız açıklamada
kullanıyorsanız `TYPE_CHECKING` altında içe aktarın:

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rewloy.types import IssuePassBody
```

### Kimlik

| İstemci | Ne için |
|---|---|
| `Rewloy(api_key="rwk_…")` | API anahtarı: kasa, e-ticaret, kendi sisteminiz |
| `Rewloy(staff_session="rws_…", merchant=…)` | ekip oturumu: bir kişinin işletme uygulaması |
| `Rewloy(holder_session="rwh_…")` | kart sahibi oturumu: Rewloy Cüzdan gibi müşteri uygulamaları |
| `Rewloy()` | kimlik istemeyen uç noktalar: giriş, katılım, kod |

`merchant`, ekip oturumu birden fazla işletmede koltuk taşıyorsa hangi işletme
için çalıştığını söyler (`Rewloy-Merchant`). Her çağrıda `merchant=` ile
değiştirilebilir. Oturumlar kimliksiz bir istemciyle açılır:

```python
oturum = Rewloy().login(body={"email": eposta, "password": parola})
ekip = Rewloy(staff_session=oturum["token"], merchant=isletme_id)
if oturum["mfaRequired"]:
    ekip.prove_mfa(body={"code": "123456"})
```

Bir işlem istemcinin kimlik türünü kabul etmiyor ama kimliksiz de çalışıyorsa
(örneğin `login`), istemci onu kimliksiz çağırır. API, işlemin kabul etmediği
bir kimliği reddeder (`CREDENTIAL_NOT_ALLOWED`). Kimlik `repr`de görünmez.

Diğer seçenekler:
- `base_url` (varsayılan `https://app.rewloy.com`; sonuna `/v1` eklemeniz ya da eklememeniz fark etmez: `https://app.rewloy.com/v1` de olur, kütüphane `/v1`i kendisi ekler);
- `timeout` (saniye; varsayılan 60, `0` sınırsız);
- `max_retries` (2);
- `transport`: HTTP katmanı (bkz. [Taşıma](#taşıma-ve-test-etmek));
- `user_agent`: gönderilen `User-Agent`a eklenir, örneğin `"KasaPOS/4.2"`;
- `sleep`: yeniden denemeler arasındaki beklemeyi değiştirir (testler için).

İstemci iş parçacıkları arasında paylaşılabilir. `with Rewloy(...) as rewloy:`
ya da `rewloy.close()` taşımanın tuttuklarını bırakır.

### Başka bir adres (staging)

API'nin başka bir kopyasına (kendi staging ortamınız ya da bir vekil sunucu)
`base_url` ile bağlanılır:

```python
rewloy = Rewloy(
    api_key=os.environ["REWLOY_API_KEY"],
    base_url="https://rewloy-staging.ornek.com",   # sonuna /v1 yazsanız da olur
)
```

Gerçek müşterilere dokunmadan denemek için adres değiştirmeniz gerekmez:
[test modu](#test-modu) aynı adreste, ayrı bir test ortamıyla çalışır.

## Kart vermek ve kasada işlem

```python
sonuc = rewloy.issue_pass(
    body={"programId": program_id, "email": "ayse@ornek.com", "firstName": "Ayşe", "kvkkConsent": True},
)
seri, kart_adresi = sonuc["serial"], sonuc["cardUrl"]

islem = rewloy.pass_action(
    seri,
    body={"action": "earn-stamps", "locationId": sube_id, "count": 1},
    idempotency_key=f"kasa3-z0187-fis{fis_no}",   # aşağıya bakın
)
if islem.get("duplicate"):
    print("Bu işlem zaten yazılmış")
```

### Satış: `record_sale`

Kasa ya da kendi yazılımınız için en kolay yol `record_sale`dir: "bu satış
oldu, sen yaz". Ödenen toplamı (kartın para biriminde, kuruş) gönderirsiniz;
ne yazılacağına kartın türü ve programın kendi kuralı karar verir. Kartın
türünü bilmeniz gerekmez.

```python
kart = rewloy.get_pass(seri)
# Kartın türüne özgü alanlar; `balance` yerine bunları okuyun.
if "stamps" in kart:
    print(f"{kart['stamps']['count']} / {kart['stamps']['max']} damga")
if "points" in kart:
    print(f"{kart['points']} puan")
if "money" in kart:
    print(kart["money"]["amountMinor"] / 100, kart["money"]["currency"])
musteri = kart.get("customer")   # yalnız customers.read yetkisiyle; yoksa None
print(kart["programName"], musteri["name"] if musteri else None)

# Fiş numarası anahtar olamaz: kasa + Z no + fiş no, ya da satışla saklanan bir UUID.
anahtar = f"kasa3-z0187-fis{fis_no}"
satis = rewloy.record_sale(
    seri,
    body={
        "locationId": sube_id,
        "amountMinor": 4550,          # 45,50: kartın para biriminde (kart["currency"]), kuruş
        "currency": kart["currency"], # isteğe bağlı güvence: uyuşmazsa 422 CURRENCY_MISMATCH
        "reference": f"fis-{fis_no}", # fiş numarası buraya yazılır
    },
    idempotency_key=anahtar,
)
if satis["applied"] == "none":
    print("Yazılan bir şey yok:", satis.get("reason"))
else:
    print(satis["credited"], satis["applied"], "yazıldı, bakiye", satis["balance"])
if satis["rewardReady"]:
    print("Ödül hazır")
```

`GET /v1/passes/{serial}` ayrıca `actions` (kartın aldığı kasa işlemleri ve
şimdi yapılıp yapılamayacakları) ve `sale` (bir satışın bu kartta ne
yazacağı) alanlarını verir.

**İade.** `reverse_sale` bir satışın karta yazdığını geri alır; satışı
yazarken gönderdiğiniz anahtarla (`saleKey`) ya da `reference`la bulur:

```python
geri = rewloy.reverse_sale(seri, body={"saleKey": anahtar, "locationId": sube_id})
print(geri["reversed"], geri["applied"], "geri alındı, bakiye", geri["balance"])
```

Bir satış bir kez geri alınır (tekrar `duplicate: true` döner). Kazanılan
kullanılmışsa (ödüle ya da harcamaya gitmişse) `409 SALE_ALREADY_SPENT` gelir ve
hiçbir şey yazılmaz.

### `Idempotency-Key`

`record_sale`, `pass_action`, `send_campaign` ve `refund_shop_redemption` bir
`Idempotency-Key` **ister**: API'nin tanımında (OpenAPI) bu başlık bu işlemlerde
zorunludur, bu yüzden `idempotency_key` bu metotlarda zorunlu bir anahtar
sözcük argümanıdır (vermezseniz `TypeError`; `request()` ile çağırırken
`ValueError`, ikisi de istek göndermeden). Kütüphane **sizin yerinize anahtar
üretmez**. Üretilmiş rastgele bir anahtar yalnızca tek çağrının yeniden
denemelerini korurdu: uygulama çöküp yeniden başlarsa yeni bir anahtar çıkar ve
satış ikinci kez yazılabilirdi. Anahtarı kendiniz üretip satışla birlikte
saklayın. Anahtar 8–64 karakterlik görünür ASCII olmalıdır (0x21–0x7E: harf,
rakam ve noktalama; boşluk, Türkçe harf ya da `fiş` gibi ASCII dışı karakter
olmaz); aksi halde kütüphane yine istek göndermeden `ValueError` fırlatır.
Başlığın isteğe bağlı olduğu işlemlerde (örneğin `issue_pass`) anahtar
verilmezse kütüphane bir UUID üretir ve aynı çağrının her denemesinde aynısını
gönderir.

- **Anahtar bir kimlik için kalıcı olarak tekildir** (8–64 karakter; defterden
  hiç silinmez). Aynı anahtarla aynı isteğin tekrarı ikinci kez yazmaz ve
  ilk sonucu `duplicate: true` ile döndürür. Aynı anahtar başka bir gövdeyle
  `422 IDEMPOTENCY_KEY_REUSED` alır.
- **Fiş numarası tek başına anahtar olamaz:** yazarkasa fiş numaraları Z
  raporundan sonra yeniden başlar. Kasa + Z no + fiş no birleşimi
  (`kasa3-z0187-fis0042`) ya da satışla birlikte saklanıp tekrarda yeniden
  gönderilen bir UUID kullanın.
- **Fiş numarası `reference` alanına** yazılır; müşterinin geçmişinde ve işlem
  dökümünde görünür.

## Sayfalama

```python
for musteri in rewloy.paginate("listCustomers", query={"consent": "yes", "limit": 200}):
    print(musteri["displayName"], musteri["identifiers"])
```

`paginate` sayfalı her listeyi (`page`/`limit` ve `meta`) öğe öğe dolaşır ve
son sayfada durur; tembeldir, bıraktığınız yerde istek de durur. Adreste
parametresi olan listelere `path={"id": …}` verilir. Tek bir sayfa için
metodun kendisi yeter: `sayfa = rewloy.list_customers(query={"page": 2})`
(`sayfa.data`, `sayfa.meta`).

## Canlı akış

```python
with rewloy.live_feed() as akis:
    for olay in akis:
        if olay.event == "event":
            ev = olay.json()
            print(ev["kind"], ev["location"], ev["program"], ev["delta"], ev["unit"], ev["name"])
```

`live_feed` (işletmenin tezgâh akışı) ve `holder_card_events` (kart sahibinin
kartındaki değişiklik) sunucu olayları (`text/event-stream`) yayınlar.
`rewloy.stream("liveFeed", …)` aynı işi görür. Her olay `event`, `data` ve
`id` taşır; `json()` `data`yı ayrıştırır.

- **Yeniden bağlanma.** Bağlantı koparsa akış kendiliğinden yeniden bağlanır:
  sunucunun `retry:` süresi kadar bekler, bir olay `id` taşıdıysa
  `Last-Event-ID` gönderir. `reconnect=False` bunu kapatır.
- **Sessiz bağlantı.** API 25 saniyede bir `: hb` gönderir; 60 saniye hiç veri
  gelmezse bağlantı kopmuş sayılır (`idle_timeout=`).
- **Durdurmak:** döngüden `break` (bağlantı hemen kapanır), `with` bloğundan
  çıkmak ya da başka bir iş parçacığından `akis.close()`.
- **Bitiren hatalar.** Yeniden bağlanmanın düzeltemeyeceği bir hata (`401`,
  `403`, `404`) akışı `RewloyError` ile bitirir.

## Webhook doğrulama

Rewloy her teslimi imzalar:

```
Rewloy-Signature: t=<unix saniye>,v1=<hex HMAC-SHA256(sır, "<t>.<ham gövde>")>
```

`verify_webhook` imzayı **ham gövdeyle** ve webhook oluşturulurken bir kez
gösterilen sırla (`whsec_…`) doğrular:
- karşılaştırmayı `hmac.compare_digest` ile sabit sürede yapar;
- `t` şimdiden 300 saniyeden (`tolerance=`) uzaksa reddeder;
- gövdeyi ayrıştırılmış olarak (`dict`) döndürür.

Webhook'u panelden ya da API'den ekleyebilirsiniz. `webhooks.manage` yetkili
bir API anahtarı `create_webhook`, `list_webhooks`, `get_webhook`,
`set_webhook_status`, `test_webhook` ve `list_webhook_deliveries`i çağırabilir;
`webhook_events` abone olunabilecek olayları söyler. Sır (`secret`) yalnız
`create_webhook` yanıtında gelir, saklayın:

```python
yeni = rewloy.create_webhook(
    body={"url": "https://ornek.com/rewloy/webhook", "events": ["pass.activity", "pass.voided"]},
)
sir = yeni["secret"]
rewloy.test_webhook(yeni["webhook"]["id"])   # webhook.test olayı gönderir
```

Adres herkese açık bir `https` adresi olmalıdır (test ortamında da);
yerelde bir tünel kullanın.

Tutmazsa `WebhookSignatureError` atar: 400 ile yanıtlayın ve hiçbir işlem
yapmayın. Gövde mutlaka ham olmalıdır (`str` ya da `bytes`). JSON olarak
ayrıştırılıp yeniden yazılan bir gövde imzayı tutturmaz; ayrıştırılmış bir
`dict` verirseniz `TypeError` alırsınız.

Flask:

```python
import os
from flask import Flask, request
from rewloy import WebhookSignatureError, verify_webhook

app = Flask(__name__)

@app.post("/rewloy/webhook")
def rewloy_webhook():
    try:
        olay = verify_webhook(
            request.get_data(),
            request.headers.get("Rewloy-Signature"),
            os.environ["REWLOY_WEBHOOK_SECRET"],
        )
    except WebhookSignatureError:
        return "", 400
    # Rewloy-Delivery bir teslimin her denemesinde aynıdır: işlediyseniz atlayın.
    if daha_once_islendi(request.headers.get("Rewloy-Delivery")):
        return "", 200
    if olay["type"] == "pass.activity":
        print(olay["data"]["card"], olay["data"]["kind"], olay["data"]["delta"])
    return "", 200
```

FastAPI (Django'da ham gövde `request.body`dir):

```python
from fastapi import FastAPI, HTTPException, Request

app = FastAPI()

@app.post("/rewloy/webhook")
async def rewloy_webhook(request: Request) -> dict[str, bool]:
    try:
        olay = verify_webhook(await request.body(), request.headers.get("rewloy-signature"), SIR)
    except WebhookSignatureError:
        raise HTTPException(status_code=400)
    ...
    return {"ok": True}
```

Başlıklar:
- `Rewloy-Event`: olay türü (`pass.issued`, `pass.activity`, `pass.voided`,
  `webhook.test`); gövdedeki `type` ile aynı.
- `Rewloy-Delivery`: teslimin kimliği. Teslim "en az bir kez"dir: çift gelen
  teslimi bununla ayıklayın.

Gövde kişinin iletişim bilgisini taşımaz; kişiyi `customer_id` ile API'den
okuyun. 2xx dışı bir yanıt yaklaşık 45 saat boyunca 8 kez yeniden denenir ve
her deneme yeni bir `t` ile imzalanır. Sonuç `PassEvent` ya da
`WebhookTestEvent` tipindedir: `olay["type"]` ile `mypy` türü daraltır, bilinmeyen
yeni bir tür için bir `else` dalı bırakın. Kendi işleyicinizi test etmek için
`sign_webhook(govde, sir)` aynı başlığı üretir.

## Hatalar ve yeniden deneme

```python
from rewloy import RateLimitError, RewloyError

try:
    rewloy.pass_action(
        seri,
        body={"action": "spend", "locationId": sube_id, "amountMinor": 5000},
        idempotency_key=f"kasa3-z0187-fis{fis_no}",
    )
except RateLimitError as err:
    print(f"{err.retry_after} saniye sonra yeniden deneyin")
except RewloyError as err:
    if err.code == "INSUFFICIENT_BALANCE":
        print(err.detail)
    else:
        raise
```

`RewloyError` şunları taşır:
- `status`: HTTP durumu;
- `code`: API'nin sabit kodu ([hata kodları](https://rewloy.com/gelistiriciler/hatalar));
  kodunuz buna göre davranmalı (`rewloy.types.ErrorCode` bugünkü kodları sayar);
- `title`: kodun katalogdaki başlığı;
- `detail`: API'nin açıklaması (Türkçe, değişebilir);
- `details`: varsa ayrıntı; doğrulama hatasında `[{"field", "rule", "message"}]`;
- `request_id`: `x-request-id`; destek talebinde bunu verin;
- `body`, `headers`, `docs` ve `operation`.

Alt sınıflar:
- `RateLimitError`: `429`; `retry_after` saniye;
- `RewloyConnectionError`: yanıt gelmedi (`status` 0, `code`
  `CONNECTION_ERROR`);
- `RewloyTimeoutError`: zaman aşımı (`TIMEOUT`).

Rewloy'un olmayan bir hata gövdesi (örneğin bir vekil sunucunun 502 sayfası)
`HTTP_502` gibi bir kodla gelir. Yanlış kullanım (yanlış önekli bir anahtar,
eksik adres parametresi) Python'un `ValueError`ı ya da `TypeError`ıdır.

**Yeniden deneme.** Şunlar en çok `max_retries` kez (varsayılan 2) yeniden
denenir: bağlantı hatası, zaman aşımı, `429`, `502`, `503`, `504` ve
Cloudflare'in `520`–`524` hataları.
- **Bekleme:** üstel ve rastgele (0,5 sn, 1 sn, 2 sn… en çok 8 sn); yanıt
  `Retry-After` taşıyorsa o kadar. `Retry-After` 60 saniyeden uzunsa
  beklenmez, hata size gelir.
- **Yalnız tekrarı güvenli istekler:** `GET`, `PUT`, `DELETE` ve
  `Idempotency-Key` taşıyan `POST`. İlk istek hâlâ işlenirken gelen
  `409 IDEMPOTENCY_IN_PROGRESS` de beklenip yeniden denenir. Diğer `POST` ve
  `PATCH` istekleri hiç tekrar edilmez.
- **Süre:** her deneme `timeout` (varsayılan 60 sn) içinde bitmelidir; süre
  gövdenin tamamını kapsar.

## Kullanımdan kalkma

Kalkacak bir uç nokta en az 180 gün önceden duyurulur. O süre boyunca her
yanıtı `Deprecation`, `Sunset` ve `Link` başlıklarını taşır.

- **Uyarı.** Kütüphane her işlem için bir kez `warnings.warn` ile bir
  `DeprecationWarning` yayar. Uyarı işlemi, `Sunset` tarihini ve değişiklik
  günlüğündeki kaydı söyler; satır olarak sizin çağrınızı gösterir, bu yüzden
  Python'un varsayılan süzgeci onu `__main__` kodunda gösterir.
- **Tipler.** O metodun belge dizgisi (docstring) kaldırılacağını söyler;
  kalkacak yanıt alanları da metodun belgesinde ve tiplerde işaretlidir.
- **Yönetmek.** `python -W default` her yerde gösterir; `-W ignore::DeprecationWarning`
  ya da `warnings.filterwarnings` susturur. `-W error` ile uyarı istisna
  olurdu ama sunucu işi yapmış olurdu ve yanıt kaybolurdu: bu yüzden çağrı
  döner ve uyarı `rewloy` kaydedicisine (`logging`) yazılır.

## Yanıtın tamamı ve test modu

```python
yanit = rewloy.request(
    "sendCampaign",
    body={"body": "Bu hafta kahveler 2 damga!"},
    idempotency_key="kampanya-2026-10-03",
)
yanit.status       # 201
yanit.replayed     # True: aynı anahtarın ilk yanıtı yeniden döndü (Idempotent-Replayed)
yanit.request_id   # x-request-id
yanit.mode         # Rewloy-Mode
yanit.data         # kampanya
```

`request(işlem, …)` her işlemi çağırır (`operationId` ya da metot adıyla) ve
yanıtın tamamını döndürür: `data`, sayfalı listede `meta`, `status`,
`headers`, `request_id`, `mode` ve `replayed`. Adres parametreleri
`path={"serial": …}` ile verilir. `data` burada tipli değildir; `typing.cast`
ya da metodun kendisi.

`mode`, yanıtın `Rewloy-Mode` başlığıdır: `live` ya da `test`. Başlık yoksa
`None`. Canlı akışta aynı bilgi `akis.mode`dadır.

## Test modu

Gerçek müşterilere dokunmadan denemek için işletmenizin bir **test ortamı**
vardır: ona bağlı ayrı bir işletme (adı "· Test" ile biter); kendi
programları, müşterileri, kartları, anahtarları ve webhook'ları. Panel →
Geliştirici → "Test ortamını aç" ya da `POST /v1/test/environment`. Orada
oluşturulan anahtar `rwk_test_` ile başlar ve aynı adreste, aynı yollarla
çalışır:

```python
rewloy = Rewloy(api_key=os.environ["REWLOY_TEST_KEY"])   # rwk_test_…
yanit = rewloy.request("getPass", path={"serial": seri})
yanit.mode   # "test"
```

- Test ortamı hiçbir şey göndermez (e-posta, bildirim, SMS); kartlar
  cüzdanlara eklenmez. Gönderilmeyenler `GET /v1/test/messages` ile okunur.
- Webhook'lar teslim edilir ve `Rewloy-Test: 1` başlığıyla `"test": true`
  taşır.
- Gerçek müşteri verisini test ortamına girmeyin.

Ayrıntı: https://rewloy.com/gelistiriciler#test-ortamı

İşlem tablosu da dışa açıktır: `OPERATIONS["passAction"]` →
`OperationMeta(id, method_name, http_method, path, auth, merchant, idempotency, body, response, paged, stream, deprecated)`.

## Taşıma ve test etmek

Varsayılan taşıma `urllib`dir: bağımlılık yok, yönlendirme izlenmez (API
yönlendirmez; izlemek anahtarı başka yere taşıyabilir), yalnız `http` ve
`https`, ortam değişkenlerindeki vekil (`HTTPS_PROXY`) kullanılır. Her istek
yeni bir bağlantı açar. Bağlantı havuzu, HTTP/2 ya da kendi vekil ve sertifika
ayarlarınız için:

```python
import httpx
from rewloy import Rewloy
from rewloy.httpx_transport import HttpxTransport   # pip install "rewloy[httpx]"

rewloy = Rewloy(api_key=anahtar, transport=HttpxTransport(httpx.Client(http2=True)))
```

`transport=` aynı zamanda sahte bir API'dir: `send(request)`, `open_stream(request)`
ve `close()` olan her nesne olur. Kendi kodunuzu ağsız test etmek için:

```python
from rewloy import Headers, HttpRequest, HttpResponse, Rewloy

class SahteTasima:
    def send(self, request: HttpRequest) -> HttpResponse:
        return HttpResponse(200, "OK", Headers([("Content-Type", "application/json")]),
                            b'{"data": {"serial": "ABCD-EFGH-JKLM", "balance": 3}}')
    def open_stream(self, request: HttpRequest): raise NotImplementedError
    def close(self) -> None: pass

rewloy = Rewloy(api_key="rwk_test", transport=SahteTasima())
assert rewloy.get_pass("ABCD-EFGH-JKLM")["balance"] == 3
```

### asyncio

İstemci eşzamanlıdır (decision 18: [docs/DECISIONS.md](docs/DECISIONS.md)). Bir
`asyncio` uygulamasında iş parçacığına verin; istemci iş parçacığı güvenlidir:

```python
kart = await asyncio.to_thread(rewloy.get_pass, "ABCD-EFGH-JKLM")
```

## Geliştirme

```sh
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
python scripts/generate.py                               # canlı belgeden: openapi/openapi.json ve src/rewloy/generated/
python scripts/generate.py --file openapi/openapi.json   # kayıtlı belgeden
mypy && pytest
```

- `src/rewloy/generated/` elle düzenlenmez; üreteç `scripts/generator.py`'dir.
- Testler ağa çıkmaz: yerel bir sahte API (`http.server`) ile çalışır.
- CI her gün canlı belgeyi okur ve bir değişiklik varsa bir pull request açar.
- Kararlar: [docs/DECISIONS.md](docs/DECISIONS.md).

## Belgeler

| | |
|---|---|
| Başlarken | https://rewloy.com/gelistiriciler |
| API referansı | https://rewloy.com/gelistiriciler/api |
| OpenAPI 3.1 | https://app.rewloy.com/v1/openapi.json |
| Hata kodları | https://rewloy.com/gelistiriciler/hatalar |
| API'nin değişiklik günlüğü | https://rewloy.com/gelistiriciler/degisiklikler |
| Bu kütüphanenin değişiklikleri | [CHANGELOG.md](CHANGELOG.md) |

**Sürümler:**
- Kütüphane anlamsal sürümleme ([SemVer](https://semver.org)) kullanır. 1.0'a
  kadar arayüzü değişebilir.
- API'ye alan eklemek geriye uyumludur; kütüphanenin tipleri her gün
  güncellenir.
- Kalkacak bir uç nokta en az 180 gün önce duyurulur ve bu süre boyunca
  `Deprecation` ve `Sunset` başlıklarını taşır.

## Güvenlik

Bir güvenlik açığı bulursanız [SECURITY.md](SECURITY.md) dosyasındaki yoldan
özel olarak bildirin. Lütfen herkese açık issue açmayın.

## Lisans

[MIT](LICENSE)

---

## English

Developer docs (in Turkish): **https://rewloy.com/gelistiriciler**.

**The official Python library for the Rewloy API.**

> **Status: preview (0.x), published on PyPI. The API is stable; the
> library's interface may change until 1.0.**

The documentation of the API itself is in Turkish (links above). In short:

- Every operation of the API is a method named by its operationId in
  snake_case (`passAction` is `pass_action`), typed with `TypedDict`s from the
  OpenAPI document, which CI reads daily and regenerates from. `mypy --strict`
  passes.
- No dependencies: Python 3.9 or later and the standard library (`urllib`,
  `json`, `hmac`). An optional `httpx` transport adds pooling and HTTP/2.
- Safe retries, `Idempotency-Key` handling, pagination, server-sent events,
  webhook signature verification and deprecation warnings.

### Install

Python 3.9 or later:

```sh
pip install rewloy
```

### Use

```python
import os
from rewloy import Rewloy

rewloy = Rewloy(api_key=os.environ["REWLOY_API_KEY"])   # or staff_session=…, merchant=… or holder_session=…

created = rewloy.issue_pass(body={"programId": program_id, "email": email, "kvkkConsent": True})
sale = rewloy.record_sale(
    created["serial"],
    body={"locationId": location_id, "amountMinor": 4550, "reference": f"receipt-{receipt_no}"},   # amount in the card's currency, minor units
    idempotency_key=f"till3-z0187-r{receipt_no}",
)
```

- **Till.** `record_sale` writes a completed sale to a card (the card type and
  the programme's own rule decide what is written); `get_pass` returns the
  card's structured fields (`programName`, `currency`, `stamps`, `points`,
  `money`, `customer`); `reverse_sale` takes a refunded sale back:
  `rewloy.reverse_sale(serial, body={"saleKey": key})`.
- **Idempotency keys.** `record_sale`, `pass_action`, `send_campaign` and
  `refund_shop_redemption` need an `Idempotency-Key`: the API's OpenAPI document
  marks the header required for them, so `idempotency_key` is a required
  keyword argument (leave it out and you get a `TypeError`, or a `ValueError`
  through `request()`, before anything is sent). The client never makes one up
  for you (a generated key would not survive a restart of your app). The key
  must be 8–64 printable ASCII characters (0x21–0x7E); a non-ASCII key such as
  `fiş-0042` is refused client-side with a `ValueError` before anything is
  sent. Where the header is optional (for example `issue_pass`) the client
  still generates a UUID and reuses it on every retry of the call. A key is unique **for good per credential**: do not use the
  receipt number alone (fiscal receipt numbers restart after the Z report) but
  register + Z number + receipt number, or a UUID stored with the sale. The
  receipt number goes in `reference`.
- **Base URL.** `Rewloy(api_key=key, base_url="https://staging.example.com")`
  or `base_url="https://staging.example.com/v1"`: with or without a trailing
  `/v1` (and trailing slashes), the client appends `/v1/...` itself. Default
  `https://app.rewloy.com`.
- **Test mode.** Open the test environment (panel → Developer, or
  `POST /v1/test/environment`) and use its `rwk_test_` key at the same address:
  a separate test business that sends nothing and never reaches real
  customers. Webhooks are delivered with `Rewloy-Test: 1`.
- **Arguments.** Path parameters are positional. `query`, `body`, `merchant`,
  `idempotency_key`, `timeout` (seconds) and `max_retries` are keywords. The
  dicts use the API's own key names.
- **Results.** A method returns the answer's `data`: a `TypedDict` or list, a
  `Page` (`.data`, `.meta`) for paged lists, `None` for 204, `bytes` for files.
  Types are in `rewloy.types` (`from rewloy.types import IssuePassBody`).
- **The whole answer.** `rewloy.request("sendCampaign", body=…)` returns
  `status`, `headers`, `request_id`, `mode` (the `Rewloy-Mode` header: `live` or `test`) and `replayed` (`Idempotent-Replayed`) with `data`.
- **Pagination.** `rewloy.paginate("listCustomers", query=…)` iterates the
  items of every page, lazily.
- **Streams.** `with rewloy.live_feed() as stream: for event in stream: …`
  iterates server-sent events (`event`, `data`, `id`, `json()`). It reconnects
  with `Last-Event-ID` unless `reconnect=False`; `close()` works from another
  thread.
- **Threads and asyncio.** The client is thread-safe. It is synchronous:
  in async code use `await asyncio.to_thread(rewloy.get_pass, serial)`.
- **Testing.** `transport=` takes anything with `send()`, `open_stream()` and
  `close()`; the README above has a fake.

### Webhooks

Verify the **raw** body (`request.get_data()` in Flask, `await request.body()`
in FastAPI, `request.body` in Django) with the secret shown when the webhook
was created:

```python
event = verify_webhook(raw_body, headers.get("Rewloy-Signature"), secret)
```

- **Check.** `Rewloy-Signature: t=<unix seconds>,v1=<hex HMAC-SHA256(secret,
  "<t>.<raw body>")>` is compared with `hmac.compare_digest`, and `t` must be
  within 300 seconds.
- **Refusal.** On failure it raises `WebhookSignatureError`: answer 400.
- **Headers.** `Rewloy-Event` is the event type. `Rewloy-Delivery` is the
  same on every retry of a delivery: deduplicate on it. Delivery is at least
  once.

### Errors, retries, deprecations

- **Errors.** Failures raise `RewloyError` with `status`, `code` (the API's
  stable code), `title`, `detail`, `details`, `request_id` and `body`.
  Subclasses: `RateLimitError` (`retry_after`), `RewloyConnectionError` and
  `RewloyTimeoutError`. Misuse raises `ValueError` or `TypeError`.
- **What is retried.** Network errors, timeouts, 429, 502–504 and
  Cloudflare's 520–524, up to `max_retries` (default 2), with exponential
  backoff and jitter, honouring `Retry-After`. The timeout covers a whole
  attempt, body included.
- **Only when safe.** Only GET, PUT, DELETE, and POST with an
  `Idempotency-Key`, are retried.
- **Deprecations.** A deprecated operation's answers carry `Deprecation`,
  `Sunset` and `Link`. The client issues one `DeprecationWarning` per
  operation, attributed to your calling line. Under `-W error` the call still
  returns and the notice goes to the `rewloy` logger.

### Security and licence

Report vulnerabilities privately, as [SECURITY.md](SECURITY.md) says.
[MIT](LICENSE) licensed.

## Yeni sürüm yayımlamak / Releasing

`src/rewloy/_version.py`'deki sürümü ve CHANGELOG'u güncelleyin, commit'leyin, `v<sürüm>` etiketini gönderin. `release.yml` PyPI'a güvenilir yayıncı (trusted publishing) yoluyla, jetonsuz yayımlar.

Bump the version in `src/rewloy/_version.py` and the changelog, commit, and push a `v<version>` tag. `release.yml` publishes to PyPI through trusted publishing, with no token.
