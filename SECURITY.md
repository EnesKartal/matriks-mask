# Güvenlik politikası / Security policy

## Açık bildirimi

matriks-pii kişisel veriyi korumak için kullanılan bir bileşendir; bir sızıntı yolu (ham değerin sağlayıcıya, loglara,
metriklere veya istemciye beklenmedik biçimde gitmesi), geri çevirmenin başka bir isteğin verisini döndürmesi,
oturum jetonu/şifreleme zayıflığı veya fail-open davranışı güvenlik açığıdır.

**Herkese açık issue açmayın.** Bildirimi GitHub'ın özel açık bildirim akışıyla yapın:
deponun **Security** sekmesi → **Report a vulnerability**
(<https://github.com/MatriksData/matriks-pii/security/advisories/new>).
Bu akışı kullanamıyorsanız e-posta: **matriksiq@matriksdata.com** (konu satırına `matriks-pii security` yazın).

Bildirime şunları ekleyin:

- etkilenen sürüm (`python -c "import matriks_pii; print(matriks_pii.__version__)"`) ve LiteLLM sürümü,
- ilgili guardrail yapılandırması (sırlar çıkarılmış),
- yeniden üretme adımları. **Yalnız sentetik veri kullanın**; gerçek kişisel veri veya gerçek anahtar göndermeyin.

Bildirimi en geç 5 iş günü içinde yanıtlamayı ve düzeltme takvimini sizinle paylaşmayı hedefliyoruz. Düzeltme
yayımlanana kadar ayrıntıları gizli tutmanızı rica ederiz.

## Reporting a vulnerability (English)

Please do **not** open a public issue. Use GitHub private vulnerability reporting:
**Security** tab → **Report a vulnerability**. If you cannot use it, e-mail **matriksiq@matriksdata.com** with
`matriks-pii security` in the subject line. Include the affected version, your guardrail configuration with secrets
removed, and reproduction steps using **synthetic data only**. We aim to respond within 5 business days.

## Desteklenen sürümler

Güvenlik düzeltmeleri yalnız en son yayımlanan sürüme yapılır.

## Kapsam dışı

- LiteLLM'in kendisindeki açıklar (ör. `--detailed_debug` ile ham gövdenin loglanması): <https://github.com/BerriAI/litellm>.
- Bilinen sınırlar: README'deki "Bilinen sınırlar" (Known limitations) bölümünde belgelenmiş tespit eksikleri (ör. görsel/PDF içi metin).
  Yeni bir yanlış negatif örneği güvenlik açığı değil, normal bir issue'dur.
