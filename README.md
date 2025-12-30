# ProSearcher


ProSearcher_V11/
│
├── 📜 ProSearcher_V11.py        # (Backend) Veri toplama, analiz ve karar motoru
├── 📊 app.py                    # (Frontend) Streamlit Bilişsel Dashboard arayüzü
├── ⚙️ rules.json                 # (Config) Taksonomi, Marka Tier'ları ve Selector'lar
├── 🔒 .env                      # (Secrets) Webhook URL ve hassas ayarlar
├── 📦 requirements.txt          # (Deps) Gerekli kütüphane listesi
│
├── 🗄️ ilan_takip_v11_cognitive.db  # (Auto) Bot çalıştığında oluşacak veritabanı
└── 📝 bot_v11.log               # (Auto) Bot çalıştığında oluşacak log dosyası




Nasıl Çalıştırılır?

Kurulum: Terminale şu komutu yazarak kütüphaneleri yükleyin: pip install -r requirements.txt

Veri Toplama (Motoru Başlatma): Botu çalıştırın. Bu arka planda sürekli çalışmalı ve veri toplamalıdır. python ProSearcher_V11.py

Arayüzü Açma (Dashboard): Yeni bir terminal penceresinde arayüzü başlatın: streamlit run app.py