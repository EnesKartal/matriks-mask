# Bağımsız değerlendirme kümesi

`holdout.jsonl` (269 senaryo: 162 PII içeren, 107 tuzak) uygulama kodunu ve diğer fixture'ları **görmeyen** ayrı bir
LLM ajanı (yapay zekâ modeli) tarafından, Türk finans/aracı kurum yazılımı müşteri metinlerine benzer biçimde yazıldı. Tüm değerler sentetiktir;
TCKN/VKN/IBAN/kart etiketleri python-stdnum ile doğrulandı.

**Kör ölçüm (2026-10-28, düzeltme öncesi):** deterministik varlıklarda P≈R≈1.0 (TCKN R=0.95, TELEFON P=0.90),
KISI P=0.947 R=0.831 F2=0.852; özel nitelikli veriler çoğunlukla span sınırı farkı.

Bu ölçümden sonra genel (kümeye özel olmayan) düzeltmeler yapıldı: küçük harfli ad-soyad, form/JSON alan bağlamı,
apostroflu özel ad kanıtı, modern adlar, ülke/tarihî kişi listesi, gruplu TCKN, ayraçsız telefon kuralı, tarih/sürüm
bağlamları. Düzeltme sonrası KISI P=R=0.977. Küme artık kör değildir; `tests/test_holdout.py` yalnız gerilemeyi yakalar.
Yeni bir kör ölçüm için bu küme yerine yeni, bağımsız bir küme yazdırılmalıdır.

## holdout2.jsonl

345 senaryo (226 PII içeren, 119 tuzak), yine uygulama kodunu ve fixture'ları görmeyen ayrı bir LLM ajanı tarafından 0.3.0
kapsamına göre (Ad SOYAD, form alanları, yeni varlıklar `GIZLI_ANAHTAR`/`KONUM`/`MKK_SICIL`/`POLICE_NO`, kaçış
varyantları, özel nitelikli öz-bildirimler) yazıldı. Tüm değerler sentetiktir.

**Kör ölçüm (2026-10-28, `balanced`, düzeltme öncesi):** P=0.954 R=0.934 F2=0.938.

Genel düzeltmeler (bağlamsal kurallarda en yakın/özgül bağlam, kart markası uzunlukları, IP sürüm bağlamı, poliçe
biçimleri, JSON tırnaklı şifre, özel nitelikli öz-bildirimlerin kişiye bağlanması, kurum üyeliği, koordinasyonlu adlar,
imza bağlamı, cümle başı adres kırpması) sonrası: `balanced` P=0.991 R=0.994 F2=0.993 (3/345 satır farklı),
`strict` P=0.974 R=0.994 F2=0.990. Kalan farklar yorum meselesidir: "Velinin" (veli adı mı?), "Ramazan Usta" (unvanlı tam
ad), "kan grubu 0 Rh-" (span sınırı).
