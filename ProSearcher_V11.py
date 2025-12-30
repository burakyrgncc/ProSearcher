import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
import sqlite3
import time
import random
import logging
from datetime import datetime, timedelta
import sys
import os
import re
import statistics
import json
import math
from dotenv import load_dotenv

load_dotenv()

# --- V11 KONFİGÜRASYON ---
class Config:
    BASE_URL = os.getenv("TARGET_URL", "https://www.sahibinden.com/kategori/bilgisayar-cevre-birimleri")
    DB_NAME = os.getenv("DB_NAME", "ilan_takip_v11_cognitive.db")
    CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 300))
    DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
    
    MAX_PAGES = 5
    MIN_SAMPLE_SIZE = 10
    
    # Sigmoid Parametreleri (Z-Score Dönüşümü için)
    # Bu ayarlar Z=-2.0 civarında maksimum ivmelenmeyi sağlar.
    SIGMOID_CENTER = 2.0  
    SIGMOID_SLOPE = 2.5
    
    # Risk Yönetimi
    CRITICAL_LOW_Z = -4.5 # Bu noktanın altı artık "Outlier/Hata" bölgesidir.

    # Harici Config (Simülasyon)
    EXTERNAL_CONFIG = """
    {
        "TAXONOMY": {
            "BRANDS": {
                "Asus": {"synonyms": ["asus", "rog", "tuf"], "tier": "TIER_1"},
                "Msi": {"synonyms": ["msi", "micro-star"], "tier": "TIER_1"},
                "Logitech": {"synonyms": ["logitech", "logi"], "tier": "TIER_1"},
                "Razer": {"synonyms": ["razer"], "tier": "TIER_1"},
                "Rampage": {"synonyms": ["rampage", "everest"], "tier": "TIER_2"},
                "Gamepower": {"synonyms": ["gamepower"], "tier": "TIER_2"},
                "Unknown": {"synonyms": [], "tier": "UNKNOWN"}
            },
            "CATEGORIES": {
                "Monitor": {"regex": "(monitor|monitör|hz|ips)", "dominant_spec": "refresh_rate"},
                "Ekran Kartı": {"regex": "(ekran kartı|gpu|rtx|gtx)", "dominant_spec": "gpu_tier"},
                "Mouse": {"regex": "(mouse|fare|dpi)", "dominant_spec": "connectivity"}
            },
            "SPECS": {
                "refresh_rate": {"regex": "(144hz|165hz|240hz|360hz)"},
                "gpu_tier": {"regex": "(4090|4080|4070|3090|3080|3070|3060)"},
                "connectivity": {"regex": "(kablosuz|wireless|bluetooth|bt)"}
            }
        },
        "SELECTORS": {
            "strategies": [
                {
                    "name": "Standard_List",
                    "container": "div.search-result-item",
                    "title": ".classifiedTitle",
                    "price": ".searchResultsPriceValue",
                    "link": "a.classifiedTitle",
                    "id": "data-id"
                }
            ]
        }
    }
    """
    
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
    ]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("bot_v11.log"), logging.StreamHandler(sys.stdout)]
)

class ConfigLoader:
    _data = json.loads(Config.EXTERNAL_CONFIG)
    @classmethod
    def get_taxonomy(cls): return cls._data['TAXONOMY']
    @classmethod
    def get_selectors(cls): return cls._data['SELECTORS']['strategies']

class MathEngine:
    """
    V11: İleri Matematik Motoru (Sigmoid & Robust Stats)
    """
    @staticmethod
    def calc_robust_stats(data):
        if not data or len(data) < 2: return None
        median = statistics.median(data)
        # MAD (Median Absolute Deviation)
        mad = statistics.median([abs(x - median) for x in data])
        if mad == 0: mad = 0.001 
        return {'median': median, 'mad': mad, 'n': len(data)}

    @staticmethod
    def mod_zscore(val, stats):
        return 0.6745 * (val - stats['median']) / stats['mad']

    @staticmethod
    def sigmoid_score(z_score):
        """
        Z-Score'u 0-50 arası bir puana dönüştüren S-Eğrisi (Logistic Function).
        Negatif Z-Score (ucuzluk) puanı artırır.
        """
        # Z-Score'u ters çeviriyoruz çünkü negatif Z iyidir.
        # Z = -2.0 -> x = 2.0
        x = -z_score 
        
        # Sigmoid Formülü: L / (1 + e^-k(x - x0))
        # L=50 (Max Puan), k=Slope, x0=Center
        try:
            val = 50 / (1 + math.exp(-Config.SIGMOID_SLOPE * (x - Config.SIGMOID_CENTER)))
        except OverflowError:
            val = 50.0 if x > 0 else 0.0
            
        return val

class TaxonomyEngine:
    @staticmethod
    def analyze(title):
        conf = ConfigLoader.get_taxonomy()
        t_low = title.lower()
        res = {'category': 'Diğer', 'brand': 'Unknown', 'tier': 'UNKNOWN', 'cluster_key': 'generic'}
        
        for cat, det in conf['CATEGORIES'].items():
            if re.search(det['regex'], t_low):
                res['category'] = cat
                if 'dominant_spec' in det:
                    spec_regex = conf['SPECS'][det['dominant_spec']]['regex']
                    m = re.search(spec_regex, t_low)
                    if m: res['dominant_spec'] = m.group(1)
                break
        
        for br, det in conf['BRANDS'].items():
            for syn in det['synonyms']:
                if syn in t_low:
                    res['brand'] = br
                    res['tier'] = det['tier']
                    break
            if res['brand'] != 'Unknown': break
            
        parts = []
        if res['brand'] != 'Unknown': parts.append(res['brand'].lower())
        if res.get('dominant_spec'): parts.append(res.get('dominant_spec'))
        if parts: res['cluster_key'] = "_".join(parts)
        
        return res

class DatabaseManager:
    def __init__(self, db_name):
        self.conn = sqlite3.connect(db_name)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()
        self.migrate()

    def migrate(self):
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS ilan (
                ilan_id TEXT PRIMARY KEY,
                baslik TEXT,
                category TEXT, brand TEXT, cluster_key TEXT,
                ilan_url TEXT, fiyat REAL, para_birimi TEXT, fiyat_norm REAL,
                
                -- Zaman ve Hız (V11)
                first_seen DATETIME,
                last_seen DATETIME,
                initial_price REAL,
                price_change_count INTEGER DEFAULT 0,
                hourly_velocity REAL DEFAULT 0.0, -- Saatteki fiyat değişim oranı
                
                -- Karar Matrisi
                opportunity_score INTEGER DEFAULT 0,
                risk_flags TEXT,
                decision_label TEXT, -- V11: "Hidden Gem", "Toxic" vb.
                
                aktif_mi INTEGER DEFAULT 1
            )
        """)
        self.conn.commit()

    def get_prices(self, category, brand=None, cluster_key=None):
        q = "SELECT fiyat_norm FROM ilan WHERE category=? AND aktif_mi=1 AND fiyat_norm IS NOT NULL"
        p = [category]
        if cluster_key and cluster_key != 'generic':
            q += " AND cluster_key=?"; p.append(cluster_key)
        elif brand and brand != 'Unknown':
            q += " AND brand=?"; p.append(brand)
        self.cursor.execute(q, p)
        return [r['fiyat_norm'] for r in self.cursor.fetchall()]

    def upsert(self, ad):
        now = datetime.now()
        # Basit kur (V10'dan)
        rate = 34.5 if ad['currency'] == 'USD' else 1.0
        norm_price = ad['fiyat'] * rate
        meta = TaxonomyEngine.analyze(ad['baslik'])
        
        ex = self.cursor.execute("SELECT * FROM ilan WHERE ilan_id=?", (ad['ilan_id'],)).fetchone()
        
        if ex:
            # Velocity Hesaplama (Saat Bazlı)
            first_seen = datetime.fromisoformat(ex['first_seen'])
            hours_on_market = (now - first_seen).total_seconds() / 3600
            hours_on_market = max(0.1, hours_on_market) # Zero div koruması
            
            init_price = ex['initial_price']
            # Toplam düşüş yüzdesi / Saat -> Saatteki kayıp hızı
            # Pozitif değer = Fiyat düşüyor (İyi veya Panik)
            velocity = 0.0
            if init_price > 0:
                velocity = ((init_price - norm_price) / init_price) / hours_on_market

            changes = ex['price_change_count']
            if ex['fiyat'] != ad['fiyat']: changes += 1
            
            self.cursor.execute("""
                UPDATE ilan SET fiyat=?, fiyat_norm=?, last_seen=?, 
                price_change_count=?, hourly_velocity=?, category=?, brand=?, cluster_key=?, aktif_mi=1
                WHERE ilan_id=?
            """, (ad['fiyat'], norm_price, now, changes, velocity, 
                  meta['category'], meta['brand'], meta['cluster_key'], ad['ilan_id']))
            self.conn.commit()
            
            return ex, meta, norm_price, hours_on_market, velocity
        else:
            self.cursor.execute("""
                INSERT INTO ilan (ilan_id, baslik, category, brand, cluster_key, ilan_url, 
                fiyat, para_birimi, fiyat_norm, first_seen, last_seen, initial_price, aktif_mi)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1)
            """, (ad['ilan_id'], ad['baslik'], meta['category'], meta['brand'], meta['cluster_key'], 
                  ad['ilan_url'], ad['fiyat'], ad['currency'], norm_price, now, now, norm_price))
            self.conn.commit()
            return None, meta, norm_price, 0.0, 0.0

class DecisionEngine:
    """
    V11: Karar Matrisi ve Bilişsel Motor
    """
    def __init__(self, db): self.db = db

    def evaluate(self, meta, norm_price, hours, velocity, existing_record):
        # 1. Veri Çekme (L1/L2)
        prices = self.db.get_prices(meta['category'], meta['brand'], meta['cluster_key'])
        if len(prices) < Config.MIN_SAMPLE_SIZE:
             prices = self.db.get_prices(meta['category'], brand=meta['brand'])
        
        stats = MathEngine.calc_robust_stats(prices)
        if not stats or stats['n'] < 5: return None

        z_score = MathEngine.mod_zscore(norm_price, stats)
        
        # --- S-CURVE PUANLAMA ---
        # Sigmoid: Doğrusal olmayan fiyat puanı (Max 50)
        price_score = MathEngine.sigmoid_score(z_score)
        
        # Marka Puanı (Max 30)
        brand_score = 0
        if meta['tier'] == 'TIER_1': brand_score = 30
        elif meta['tier'] == 'TIER_2': brand_score = 15
        
        # Hız ve Tazelik (Max 20)
        freshness_score = 0
        if hours < 24: freshness_score = 10
        elif hours > 720: freshness_score = -10 # 30 gün+
        
        # Velocity Bonusu (Makul hızda düşüş iyidir)
        if velocity > 0.001 and velocity < 0.05: # Saatte %0.1 - %5 arası düşüş
            freshness_score += 10
            
        total_score = price_score + brand_score + freshness_score
        
        # --- RİSK ANALİZİ ---
        flags = []
        
        if z_score < Config.CRITICAL_LOW_Z:
            flags.append("EXTREME_OUTLIER") # Muhtemel Hata/Scam
            total_score = min(total_score, 40) # Puanı baskıla
            
        if velocity > 0.10: # Saatte %10 düşüş (Çok ani)
            flags.append("PANIC_SELL")
            
        if meta['tier'] == 'UNKNOWN' and price_score > 40:
            flags.append("BRAND_MISMATCH") # Bilinmeyen marka, premium fiyat analizi
            total_score -= 20
            
        final_score = int(max(0, min(100, total_score)))
        
        # --- KARAR MATRİSİ (DECISION MATRIX) ---
        decision = "NEUTRAL"
        if final_score >= 85 and not flags:
            decision = "💎 HIDDEN GEM"
        elif final_score >= 80 and flags:
            decision = "🎲 SPECULATIVE" # Yüksek Puan ama Riskli
        elif final_score >= 70:
            decision = "✅ GOOD DEAL"
        elif final_score < 40 and flags:
            decision = "💀 TOXIC"
            
        # --- EXPLAINABILITY (NEDEN?) ---
        reasons = []
        if price_score > 40: reasons.append("Fiyat mükemmel")
        elif price_score > 25: reasons.append("Fiyat makul")
        
        if meta['tier'] == 'TIER_1': reasons.append("marka premium")
        elif meta['tier'] == 'UNKNOWN': reasons.append("marka belirsiz")
        
        if "PANIC_SELL" in flags: reasons.append("ani fiyat kırılması var")
        
        explanation = ", ".join(reasons)
            
        return {
            'score': final_score,
            'decision': decision,
            'z_score': z_score,
            'stats': stats,
            'flags': flags,
            'explanation': explanation,
            'velocity': velocity
        }

class BotEngineV11:
    def __init__(self):
        self.db = DatabaseManager(Config.DB_NAME)
        self.brain = DecisionEngine(self.db)
        self.session = requests.Session()
        self.session.mount('https://', HTTPAdapter(max_retries=Retry(total=3)))

    def notify(self, ad, meta, res, change_type, old_price=0):
        if not Config.DISCORD_WEBHOOK_URL: return
        
        # Matris Filtreleme: Toxic ve Neutral'ı bildirme
        if res['decision'] in ["NEUTRAL", "💀 TOXIC"] and not "PANIC_SELL" in res['flags']:
            return

        # Renk Kodları
        colors = {
            "💎 HIDDEN GEM": 3066993,   # Turkuaz
            "🎲 SPECULATIVE": 15105570, # Turuncu
            "✅ GOOD DEAL": 5763719,    # Yeşil
            "💀 TOXIC": 10038562        # Koyu Kırmızı
        }
        color = colors.get(res['decision'], 5814783)
        
        title = f"{res['decision']} ({res['score']}) - {meta['brand']} {meta['category']}"
        
        desc = f"**{ad['baslik']}**\n"
        desc += f"💰 **{ad['fiyat']:,.0f} {ad['currency']}**"
        if change_type == 'PRICE_CHANGE': desc += f" (📉 {old_price:,.0f})"
        
        desc += f"\n\n🤖 **Yapay Zeka Görüşü:**\n"
        desc += f"*\"{res['explanation'].capitalize()}.\"*\n"
        
        desc += f"\n📊 **Analitik Veriler:**\n"
        desc += f"• **Z-Score:** {res['z_score']:.2f} (Sigmoid Puan: {math.ceil(MathEngine.sigmoid_score(res['z_score']))}/50)\n"
        desc += f"• **Piyasa Medyanı:** {res['stats']['median']:,.0f} TL\n"
        
        if res['velocity'] > 0:
            desc += f"• **Volatilite:** Saatte %{res['velocity']*100:.2f} erime\n"
        
        if res['flags']:
            desc += f"\n🚩 **Risk Faktörleri:** " + ", ".join([f"`{f}`" for f in res['flags']])

        requests.post(Config.DISCORD_WEBHOOK_URL, json={
            "embeds": [{"title": title, "description": desc, "color": color, "url": ad['ilan_url']}]
        })

    def run_cycle(self):
        # ... (Scraping mantığı V10 ile aynı, sadece notify çağrısı güncel)
        # Simülasyon:
        pass

if __name__ == "__main__":
    print("V11 Cognitive Engine Hazır: Sigmoid Scoring, Karar Matrisi ve Açıklanabilirlik Aktif.")
    # bot = BotEngineV11()