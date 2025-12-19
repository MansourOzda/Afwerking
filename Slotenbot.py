"""
Bot Telegram pour gestion des retours d'intervention de serrurerie

INSTALLATION:
pip install python-telegram-bot>=20.0

LANCEMENT:
1. Configurer BOT_TOKEN, GROUP_ID et USER_IDS ci-dessous
2. Exécuter: python Slotenbot.py

BASE DE DONNÉES:
Le bot utilise SQLite (intégré à Python) pour stocker les retours.
Le fichier de base de données 'retours_intervention.db' sera créé automatiquement.
"""

import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import ChatMigrated
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters
)

# ==================== CONFIGURATION ====================
# Les valeurs peuvent être définies via variables d'environnement (recommandé pour production)
# ou en dur ci-dessous (pour développement local)

# 1. BOT_TOKEN : Obtenez-le depuis @BotFather sur Telegram
#    - Ouvrez Telegram et cherchez @BotFather
#    - Envoyez /newbot et suivez les instructions
#    - Copiez le token reçu (ex: "123456789:ABCdefGHIjklMNOpqrsTUVwxyz")
BOT_TOKEN = os.getenv("BOT_TOKEN", "8280174350:AAF-CpOguFGjfzl0mMpinynB2VWCRSSMFT4")

# 2. GROUP_ID : ID du groupe Telegram où le bot fonctionnera
#    Pour obtenir l'ID du groupe :
#    - Ajoutez @userinfobot au groupe et envoyez /start
#    - Il vous donnera l'ID du chat (négatif pour les groupes, ex: -1001234567890)
#    OU
#    - Ajoutez @RawDataBot au groupe et regardez "chat":{"id":-1001234567890}
GROUP_ID = int(os.getenv("GROUP_ID", "-5071208306"))  # ID du groupe Telegram (négatif pour les groupes)

# 3. USER_IDS : Liste des user_id autorisés à utiliser le bot
#    Pour obtenir votre user_id :
#    - Parlez à @userinfobot en privé et envoyez /start
#    - Il vous donnera votre ID (ex: 123456789)
#    - Ajoutez l'ID de chaque serrurier autorisé dans la liste
#    Format pour variable d'environnement : "395799444,123456789" (séparés par des virgules)
USER_IDS_STR = os.getenv("USER_IDS", "395799444")
USER_IDS = [int(uid.strip()) for uid in USER_IDS_STR.split(",") if uid.strip()]

# Nom de la base de données
# Utiliser le volume Railway si disponible (/data), sinon répertoire local
DB_PATH = os.getenv("DB_PATH", "retours_intervention.db")
DB_NAME = DB_PATH

# ==================== BASE DE DONNÉES ====================

@contextmanager
def get_db_connection():
    """Context manager pour la connexion à la base de données avec fermeture garantie"""
    # Créer le répertoire parent si nécessaire (pour le volume Railway /data)
    if os.path.dirname(DB_NAME):
        os.makedirs(os.path.dirname(DB_NAME), exist_ok=True)
    
    # Timeout de 10 secondes pour éviter les blocages prolongés
    # Si la base est verrouillée par une autre opération, attendre max 10s
    conn = sqlite3.connect(DB_NAME, timeout=10.0)
    conn.row_factory = sqlite3.Row  # Permet l'accès par nom de colonne
    try:
        yield conn
    finally:
        conn.close()  # Fermeture garantie même en cas d'erreur

def init_database():
    """Initialise la base de données SQLite"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS retours (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                nom_client TEXT NOT NULL,
                adresse TEXT NOT NULL,
                description TEXT NOT NULL,
                materiel TEXT NOT NULL,
                date TEXT NOT NULL,
                date_creation TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(message_id, chat_id)
            )
        ''')
        # Migrations pour bases existantes
        try:
            cursor.execute('ALTER TABLE retours ADD COLUMN chat_id INTEGER')
            conn.commit()
        except sqlite3.OperationalError:
            pass
        
        try:
            cursor.execute('ALTER TABLE retours ADD COLUMN statut TEXT DEFAULT "en_attente"')
            conn.commit()
        except sqlite3.OperationalError:
            pass
        
        # Créer des index pour améliorer les performances des requêtes fréquentes
        # Index sur chat_id : utilisé dans presque toutes les requêtes
        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_chat_id ON retours(chat_id)')
        except sqlite3.OperationalError:
            pass
        
        # Index sur message_id et chat_id (composite) : utilisé pour les recherches par retour spécifique
        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_message_chat ON retours(message_id, chat_id)')
        except sqlite3.OperationalError:
            pass
        
        # Index sur statut : utilisé pour filtrer par statut
        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_statut ON retours(statut)')
        except sqlite3.OperationalError:
            pass
        
        # Index sur date_creation : utilisé pour le tri chronologique
        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_date_creation ON retours(date_creation DESC)')
        except sqlite3.OperationalError:
            pass
        
        conn.commit()
        # La connexion se ferme automatiquement grâce au context manager

def add_retour_to_db(message_id: int, chat_id: int, nom: str, adresse: str, description: str, materiel: str, date: str):
    """Ajoute un retour à la base de données"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO retours (message_id, chat_id, nom_client, adresse, description, materiel, date, statut)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (message_id, chat_id, nom, adresse, description, materiel, date, "en_attente"))
        conn.commit()
        # La connexion se ferme automatiquement grâce au context manager

def update_retour_in_db(message_id: int, chat_id: int, field: str, value: str):
    """Met à jour un champ d'un retour dans la base de données (spécifique au groupe)"""
    # Liste des champs autorisés pour éviter l'injection SQL
    ALLOWED_FIELDS = {'description', 'materiel', 'nom_client', 'adresse', 'date'}
    if field not in ALLOWED_FIELDS:
        raise ValueError(f"Champ non autorisé: {field}. Champs autorisés: {', '.join(ALLOWED_FIELDS)}")
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        # Construire la requête de manière sécurisée avec validation du champ
        query = f'UPDATE retours SET {field} = ? WHERE message_id = ? AND chat_id = ?'
        cursor.execute(query, (value, message_id, chat_id))
        conn.commit()
        # La connexion se ferme automatiquement grâce au context manager

def delete_retour_from_db(message_id: int, chat_id: int):
    """Supprime un retour de la base de données (spécifique au groupe)"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM retours WHERE message_id = ? AND chat_id = ?', (message_id, chat_id))
        conn.commit()
        # La connexion se ferme automatiquement grâce au context manager

def get_all_retours(chat_id: int) -> List[sqlite3.Row]:
    """Récupère tous les retours d'un groupe spécifique"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM retours WHERE chat_id = ? ORDER BY date_creation DESC', (chat_id,))
        retours = cursor.fetchall()
        # Convertir les Row en list pour compatibilité avec le code existant
        return list(retours)

def get_retours_paginated(chat_id: int, page: int = 0, per_page: int = 10) -> tuple:
    """Récupère les retours paginés"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        offset = page * per_page
        
        # Récupérer le total
        cursor.execute('SELECT COUNT(*) FROM retours WHERE chat_id = ?', (chat_id,))
        total = cursor.fetchone()[0]
        
        # Récupérer la page
        cursor.execute('SELECT * FROM retours WHERE chat_id = ? ORDER BY date_creation DESC LIMIT ? OFFSET ?', 
                       (chat_id, per_page, offset))
        retours = cursor.fetchall()
        # Convertir les Row en list pour compatibilité
        retours_list = list(retours)
    
    total_pages = (total + per_page - 1) // per_page if total > 0 else 0
    return retours_list, total, total_pages

def update_statut_in_db(message_id: int, chat_id: int, statut: str):
    """Met à jour le statut d'un retour"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE retours SET statut = ? WHERE message_id = ? AND chat_id = ?', (statut, message_id, chat_id))
        conn.commit()
        # La connexion se ferme automatiquement grâce au context manager

def get_retour_by_message_id(message_id: int, chat_id: int) -> Optional[sqlite3.Row]:
    """Récupère un retour par son message_id et chat_id"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM retours WHERE message_id = ? AND chat_id = ?', (message_id, chat_id))
        retour = cursor.fetchone()
        return retour

def get_statut_from_retour(retour: Tuple) -> str:
    """Extrait le statut d'un retour (index 9 dans le tuple)"""
    if len(retour) > 9 and retour[9]:
        return retour[9]
    return "en_attente"

# ==================== CONSTANTES ====================

# États pour ConversationHandler
(SELECTING_ACTION,
 COLLECTING_ADRESSE,
 COLLECTING_DESCRIPTION,
 COLLECTING_MATERIEL,
 COLLECTING_EXTRA_INFO,
 MODIFYING_FIELD) = range(6)

# ==================== LOGGING ====================

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== VÉRIFICATIONS DE SÉCURITÉ ====================

def is_authorized_user(update: Update) -> bool:
    """Vérifie si l'utilisateur est autorisé - DÉSACTIVÉ : tous autorisés"""
    return True  # Tous les utilisateurs peuvent utiliser le bot

def is_authorized_group(update: Update) -> bool:
    """Vérifie si le message provient du groupe autorisé - DÉSACTIVÉ : tous les groupes autorisés"""
    return True  # Tous les groupes sont autorisés

def check_authorization(update: Update) -> bool:
    """Vérifie l'autorisation - DÉSACTIVÉ : tout le monde peut utiliser le bot"""
    return True  # Pas de restriction

# ==================== FONCTIONS UTILITAIRES ====================

async def handle_chat_migration(func, *args, **kwargs):
    """Gère les migrations de groupe vers supergroupe en réessayant avec le nouveau chat_id"""
    try:
        return await func(*args, **kwargs)
    except ChatMigrated as e:
        # Le groupe a été migré vers un supergroupe, utiliser le nouveau chat_id
        logger.info(f"Groupe migré vers supergroupe. Nouveau chat_id: {e.migrate_to_chat_id}")
        # Remplacer le chat_id dans les kwargs si présent
        if 'chat_id' in kwargs:
            kwargs['chat_id'] = e.migrate_to_chat_id
        # Réessayer avec le nouveau chat_id
        return await func(*args, **kwargs)

def escape_markdown(text: str) -> str:
    """Échappe les caractères spéciaux Markdown"""
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text

def format_date_creation(date_creation_str: Optional[str]) -> str:
    """Formate la date de création de manière lisible"""
    if not date_creation_str:
        return "Onbekend"
    
    try:
        # Parser la date depuis le format SQLite (YYYY-MM-DD HH:MM:SS)
        if isinstance(date_creation_str, str):
            dt = datetime.strptime(date_creation_str.split('.')[0], '%Y-%m-%d %H:%M:%S')
        else:
            dt = date_creation_str
        
        # Formater en néerlandais : "19 dec 2024 om 14:30"
        mois_nl = ['jan', 'feb', 'mrt', 'apr', 'mei', 'jun', 'jul', 'aug', 'sep', 'okt', 'nov', 'dec']
        mois = mois_nl[dt.month - 1]
        return f"{dt.day} {mois} {dt.year} om {dt.hour:02d}:{dt.minute:02d}"
    except (ValueError, AttributeError, IndexError):
        return str(date_creation_str) if date_creation_str else "Onbekend"

def format_retour_message(adresse: str, description: str, 
                         materiel: str, statut: str = "en_attente", 
                         date_creation: Optional[str] = None,
                         extra_info: Optional[str] = None) -> str:
    """Formate le message de retour d'intervention"""
    status_emoji = "✅" if statut == "fait" else "⏳"
    status_text = "Gedaan" if statut == "fait" else "In afwachting"
    
    message = "🔁 AFWERKING\n\n"
    message += f"Adres : {adresse}\n"
    message += f"Materiaal : {materiel}\n"
    
    # Ajouter extra_info seulement s'il existe
    if extra_info:
        message += f"Extra informatie : {extra_info}\n"
    
    message += f"{status_emoji} Status : {status_text}\n"
    
    # Ajouter la date de création si disponible
    date_formatee = format_date_creation(date_creation)
    message += f"📅 Gemaakt op : {date_formatee}"
    
    return message

def parse_retour_message(message_text: str) -> Dict[str, str]:
    """Parse un message de retour pour extraire les données"""
    data = {}
    try:
        lines = message_text.split('\n')
        for line in lines:
            line = line.strip()
            if line.startswith('Klant :'):
                data['nom'] = line.replace('Klant :', '').strip()
            elif line.startswith('Adres :'):
                data['adresse'] = line.replace('Adres :', '').strip()
            elif line.startswith('Te doen :'):
                # Ancien format, garder pour compatibilité
                data['description'] = line.replace('Te doen :', '').strip()
            elif line.startswith('Extra informatie :'):
                # Nouveau format
                data['extra_info'] = line.replace('Extra informatie :', '').strip()
            elif line.startswith('Materiaal :'):
                data['materiel'] = line.replace('Materiaal :', '').strip()
    except Exception as e:
        logger.error(f"Erreur parsing message: {e}")
    return data

def get_retour_keyboard(statut: str = "en_attente") -> InlineKeyboardMarkup:
    """Retourne le clavier pour un retour (modifier/supprimer/changer statut)"""
    status_button_text = "✅ Markeren als gedaan" if statut == "en_attente" else "⏳ Markeren als in afwachting"
    status_callback = "statut_fait" if statut == "en_attente" else "statut_attente"
    
    keyboard = [
        [InlineKeyboardButton("✏️ Bewerken", callback_data="modifier_retour")],
        [InlineKeyboardButton(status_button_text, callback_data=status_callback)],
        [InlineKeyboardButton("🗑 Verwijderen", callback_data="supprimer_retour")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_pagination_keyboard(page: int, total_pages: int, base_callback: str = "voir_retours_page") -> InlineKeyboardMarkup:
    """Retourne le clavier de pagination"""
    keyboard = []
    
    if total_pages > 1:
        row = []
        if page > 0:
            row.append(InlineKeyboardButton("◀️ Vorige", callback_data=f"{base_callback}_{page-1}"))
        if page < total_pages - 1:
            row.append(InlineKeyboardButton("Volgende ▶️", callback_data=f"{base_callback}_{page+1}"))
        if row:
            keyboard.append(row)
        
        keyboard.append([InlineKeyboardButton(f"Pagina {page+1}/{total_pages}", callback_data="noop")])
    
    keyboard.append([InlineKeyboardButton("🔙 Terug naar menu", callback_data="menu_principal")])
    
    return InlineKeyboardMarkup(keyboard)

def get_liste_statut_keyboard(retours: List, page: int, total_pages: int, chat_id: int) -> InlineKeyboardMarkup:
    """Retourne le clavier avec les boutons pour changer le statut de chaque retour"""
    keyboard = []
    
    # Ajouter un bouton pour chaque retour de la page
    for retour in retours:
        message_id = retour[1]  # message_id est à l'index 1
        adresse = retour[4]  # adresse est à l'index 4
        statut = get_statut_from_retour(retour)
        
        # Texte du bouton : adresse + emoji statut + action
        status_emoji = "✅" if statut == "fait" else "⏳"
        action_text = "→ In afwachting" if statut == "fait" else "→ Gedaan"
        button_text = f"{status_emoji} {adresse[:30]}{'...' if len(adresse) > 30 else ''} {action_text}"
        
        # Callback data : changer_statut_select_<message_id>_<page> pour garder la page actuelle
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"changer_statut_select_{message_id}_{page}")])
    
    # Pagination si nécessaire
    if total_pages > 1:
        row = []
        if page > 0:
            row.append(InlineKeyboardButton("◀️ Vorige", callback_data=f"changer_statut_page_{page-1}"))
        if page < total_pages - 1:
            row.append(InlineKeyboardButton("Volgende ▶️", callback_data=f"changer_statut_page_{page+1}"))
        if row:
            keyboard.append(row)
        
        keyboard.append([InlineKeyboardButton(f"Pagina {page+1}/{total_pages}", callback_data="noop")])
    
    keyboard.append([InlineKeyboardButton("🔙 Terug naar menu", callback_data="menu_principal")])
    
    return InlineKeyboardMarkup(keyboard)

def get_menu_keyboard() -> InlineKeyboardMarkup:
    """Retourne le clavier du menu principal"""
    keyboard = [
        [InlineKeyboardButton("➕ Afwerking toevoegen", callback_data="ajouter_retour")],
        [InlineKeyboardButton("📋 Zie afwerking", callback_data="voir_retours")],
        [InlineKeyboardButton("🔄 Statut wijzigen", callback_data="changer_statut")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_modifier_keyboard() -> InlineKeyboardMarkup:
    """Retourne le clavier pour modifier un retour"""
    keyboard = [
        [InlineKeyboardButton("Adres bewerken", callback_data="modif_adresse")],
        [InlineKeyboardButton("Beschrijving bewerken", callback_data="modif_description")],
        [InlineKeyboardButton("Materiaal bewerken", callback_data="modif_materiel")],
        [InlineKeyboardButton("❌ Annuleren", callback_data="annuler_modif")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_confirmation_keyboard() -> InlineKeyboardMarkup:
    """Retourne le clavier de confirmation de suppression"""
    keyboard = [
        [
            InlineKeyboardButton("✅ Bevestigen", callback_data="confirmer_suppression"),
            InlineKeyboardButton("❌ Annuleren", callback_data="annuler_suppression")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_cancel_keyboard() -> InlineKeyboardMarkup:
    """Retourne le clavier avec le bouton Annuler pendant la saisie"""
    keyboard = [
        [InlineKeyboardButton("❌ Annuleren", callback_data="annuler_ajout")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_cancel_keyboard_with_skip() -> InlineKeyboardMarkup:
    """Retourne le clavier avec bouton Passer et Annuler (pour extra_info optionnel)"""
    keyboard = [
        [InlineKeyboardButton("⏭️ Passer", callback_data="passer_extra_info")],
        [InlineKeyboardButton("❌ Annuleren", callback_data="annuler_ajout")]
    ]
    return InlineKeyboardMarkup(keyboard)

# ==================== HANDLERS ====================

async def update_status_message(context: ContextTypes.DEFAULT_TYPE, current_question: str, show_skip: bool = False):
    """Met à jour le message de statut avec les réponses déjà données"""
    retour = context.user_data.get('retour', {})
    message_id = context.user_data.get('status_message_id')
    chat_id = context.user_data.get('status_chat_id')  # Utiliser chat_id pour le groupe
    
    if not message_id or not chat_id:
        return
    
    status_text = "📝 **Afwerking toevoegen**\n\n"
    
    if retour.get('adresse'):
        status_text += f"📍 Adres : {escape_markdown(retour['adresse'])}\n"
    else:
        status_text += "📍 Adres : _In afwachting..._\n"
    
    if retour.get('materiel'):
        status_text += f"📦 Materiaal : {escape_markdown(retour['materiel'])}\n"
    elif 'adresse' in retour:
        status_text += "📦 Materiaal : _In afwachting..._\n"
    
    if retour.get('extra_info'):
        status_text += f"ℹ️ Extra informatie : {escape_markdown(retour['extra_info'])}\n"
    elif 'materiel' in retour:
        status_text += "ℹ️ Extra informatie : _Optioneel..._\n"
    
    status_text += f"\n💬 {escape_markdown(current_question)}"
    
    try:
        keyboard = get_cancel_keyboard_with_skip() if show_skip else get_cancel_keyboard()
        await context.bot.edit_message_text(
            chat_id=chat_id,  # Dans le groupe
            message_id=message_id,
            text=status_text,
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
    except ChatMigrated as e:
        # Le groupe a été migré vers un supergroupe, mettre à jour le chat_id et réessayer
        logger.info(f"Groupe migré vers supergroupe. Nouveau chat_id: {e.migrate_to_chat_id}")
        context.user_data['status_chat_id'] = e.migrate_to_chat_id
        try:
            await context.bot.edit_message_text(
                chat_id=e.migrate_to_chat_id,
                message_id=message_id,
                text=status_text,
                reply_markup=keyboard,
                parse_mode='Markdown'
            )
        except Exception as e2:
            logger.error(f"Erreur mise à jour message statut après migration: {e2}")
    except Exception as e:
        logger.error(f"Erreur mise à jour message statut: {e}")

async def annuler_ajout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler pour annuler l'ajout d'un retour"""
    query = update.callback_query
    if query:
        await query.answer()
        message_id = context.user_data.get('status_message_id')
        chat_id = context.user_data.get('status_chat_id')  # Utiliser chat_id pour le groupe
        
        # Supprimer le message de statut
        if message_id and chat_id:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
            except Exception:
                pass
        
        context.user_data.clear()
        # Envoyer la confirmation dans le groupe
        await query.message.reply_text(
            "❌ Toevoegen geannuleerd.",
            reply_markup=get_menu_keyboard()
        )

async def statut_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler pour changer le statut d'un retour"""
    query = update.callback_query
    if not query:
        return
    
    await query.answer()
    
    data = query.data
    message_id = query.message.message_id
    chat_id = query.message.chat_id
    
    nouveau_statut = "fait" if data == "statut_fait" else "en_attente"
    update_statut_in_db(message_id, chat_id, nouveau_statut)
    
    # Récupérer le retour mis à jour
    retour = get_retour_by_message_id(message_id, chat_id)
    if retour:
        statut_actuel = get_statut_from_retour(retour)
        date_creation = retour[8] if len(retour) > 8 else None
        # Utiliser description comme extra_info (pour compatibilité)
        extra_info = retour[5] if retour[5] else None
        new_text = format_retour_message(
            retour[4],  # adresse
            "",  # description vide maintenant
            retour[6],  # materiel
            statut_actuel,
            date_creation,
            extra_info  # Passer comme extra_info
        )
        try:
            await query.edit_message_text(new_text, reply_markup=get_retour_keyboard(statut_actuel))
            await query.answer("✅ Status bijgewerkt")
        except Exception as e:
            logger.error(f"Erreur mise à jour statut: {e}")
            await query.answer("❌ Fout bij het bijwerken van de status", show_alert=True)
    else:
        await query.answer("❌ Afwerking niet gevonden", show_alert=True)

async def menu_principal_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler pour retourner au menu principal"""
    query = update.callback_query
    if query:
        await query.answer()
        welcome_text = "🤖 **Welkom bij de Afwerking Bot**\n\nKies een actie:"
        try:
            await query.edit_message_text(welcome_text, reply_markup=get_menu_keyboard(), parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Erreur retour menu: {e}")
            await query.message.reply_text(welcome_text, reply_markup=get_menu_keyboard(), parse_mode='Markdown')

async def voir_retours_page_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler pour la pagination des retours"""
    query = update.callback_query
    if query and query.data:
        try:
            page = int(query.data.split("_")[-1])
            await voir_retours_handler(update, context, page)
        except (ValueError, IndexError):
            await query.answer("❌ Ongeldige pagina", show_alert=True)

async def changer_statut_page_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler pour la pagination de la liste de changement de statut"""
    query = update.callback_query
    if query and query.data:
        try:
            page = int(query.data.split("_")[-1])
            await changer_statut_handler(update, context, page)
        except (ValueError, IndexError):
            await query.answer("❌ Ongeldige pagina", show_alert=True)

async def changer_statut_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0) -> None:
    """Handler pour afficher la liste des retours avec possibilité de changer le statut"""
    query = update.callback_query
    await query.answer()
    
    if not check_authorization(update):
        return
    
    # Récupérer les retours paginés du groupe actuel
    chat_id = query.message.chat_id
    retours, total, total_pages = get_retours_paginated(chat_id, page, per_page=10)
    
    if not retours:
        message = "🔄 **Statut wijzigen**\n\n"
        message += "Geen afwerkingen geregistreerd op dit moment."
        try:
            if query:
                await query.edit_message_text(message, reply_markup=get_menu_keyboard(), parse_mode='Markdown')
            else:
                await context.bot.send_message(chat_id=chat_id, text=message, reply_markup=get_menu_keyboard(), parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Erreur édition message changer_statut: {e}")
            if query:
                await query.message.reply_text(message, reply_markup=get_menu_keyboard(), parse_mode='Markdown')
            else:
                await context.bot.send_message(chat_id=chat_id, text=message, reply_markup=get_menu_keyboard(), parse_mode='Markdown')
        return
    
    # Formater la liste des retours de la page
    message = "🔄 **Statut wijzigen**\n\n"
    message += "Kies een afwerking om de status te wijzigen:\n\n"
    
    start_idx = page * 10 + 1
    for idx, retour in enumerate(retours):
        statut = get_statut_from_retour(retour)
        status_emoji = "✅" if statut == "fait" else "⏳"
        status_text = "Gedaan" if statut == "fait" else "In afwachting"
        
        global_idx = start_idx + idx
        message += f"**{global_idx}.** {status_emoji}\n"
        message += f"📍 {retour[4]}\n"
        message += f"Status: {status_text}\n\n"
    
    message += f"_Totaal: {total} afwerking(en) - Pagina {page+1}/{total_pages}_"
    
    # Clavier avec boutons pour changer le statut
    statut_keyboard = get_liste_statut_keyboard(retours, page, total_pages, chat_id)
    
    try:
        if query:
            await query.edit_message_text(message, reply_markup=statut_keyboard, parse_mode='Markdown')
        else:
            # Ne devrait pas arriver, mais au cas où
            await context.bot.send_message(chat_id=chat_id, text=message, reply_markup=statut_keyboard, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Erreur édition message changer_statut: {e}")
        if query:
            await query.message.reply_text(message, reply_markup=statut_keyboard, parse_mode='Markdown')
        else:
            await context.bot.send_message(chat_id=chat_id, text=message, reply_markup=statut_keyboard, parse_mode='Markdown')

async def changer_statut_select_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler pour changer le statut d'un retour sélectionné depuis la liste"""
    query = update.callback_query
    if not query:
        return
    
    await query.answer()
    
    # Extraire le message_id et la page depuis le callback_data : changer_statut_select_<message_id>_<page>
    try:
        parts = query.data.split("_")
        message_id = int(parts[-2])  # avant-dernier élément
        current_page = int(parts[-1])  # dernier élément
    except (ValueError, IndexError):
        # Fallback pour compatibilité avec ancien format (sans page)
        try:
            message_id = int(query.data.split("_")[-1])
            current_page = 0
        except (ValueError, IndexError):
            await query.answer("❌ Ongeldige selectie", show_alert=True)
            return
    
    # Récupérer le chat_id depuis le message actuel (celui de la liste)
    current_chat_id = query.message.chat_id
    
    # Récupérer le retour actuel - on doit chercher dans tous les groupes
    # Mais comme on a le message_id, on peut chercher dans le groupe actuel d'abord
    retour = get_retour_by_message_id(message_id, current_chat_id)
    
    # Si pas trouvé dans le groupe actuel, chercher dans tous les groupes
    # (pour gérer le cas où on change le statut depuis un autre groupe)
    if not retour:
        # Essayer de trouver le retour en cherchant par message_id uniquement
        # Note: get_retour_by_message_id nécessite chat_id, donc on doit utiliser current_chat_id
        # Le vrai chat_id est stocké dans la base de données (index 2)
        # On va chercher dans le groupe actuel uniquement car c'est là qu'on est
        await query.answer("❌ Afwerking niet gevonden in deze groep", show_alert=True)
        return
    
    # Récupérer le chat_id du retour depuis la base de données (index 2)
    chat_id_retour = retour[2]  # chat_id est à l'index 2 dans le tuple
    
    # Inverser le statut actuel
    statut_actuel = get_statut_from_retour(retour)
    nouveau_statut = "fait" if statut_actuel == "en_attente" else "en_attente"
    
    # Mettre à jour dans la base de données (utiliser le chat_id du retour)
    update_statut_in_db(message_id, chat_id_retour, nouveau_statut)
    
    # Récupérer le retour mis à jour
    retour_updated = get_retour_by_message_id(message_id, chat_id_retour)
    if retour_updated:
        statut_final = get_statut_from_retour(retour_updated)
        date_creation = retour_updated[8] if len(retour_updated) > 8 else None
        
        # Mettre à jour le message dans le groupe (utiliser le chat_id du retour)
        # Utiliser description comme extra_info (pour compatibilité)
        extra_info = retour_updated[5] if retour_updated[5] else None
        new_text = format_retour_message(
            retour_updated[4],  # adresse
            "",  # description vide maintenant
            retour_updated[6],  # materiel
            statut_final,
            date_creation,
            extra_info  # Passer comme extra_info
        )
        
        # Rafraîchir immédiatement la liste AVANT d'essayer de modifier le message dans le groupe
        # Cela garantit que l'utilisateur voit le changement immédiatement
        status_text = "Gedaan" if statut_final == "fait" else "In afwachting"
        current_chat_id = query.message.chat_id
        retours_refresh, total_refresh, total_pages_refresh = get_retours_paginated(current_chat_id, current_page, per_page=10)
        
        if retours_refresh:
            message_refresh = "🔄 **Statut wijzigen**\n\n"
            message_refresh += "Kies een afwerking om de status te wijzigen:\n\n"
            
            start_idx_refresh = current_page * 10 + 1
            for idx, retour in enumerate(retours_refresh):
                statut_refresh = get_statut_from_retour(retour)
                status_emoji_refresh = "✅" if statut_refresh == "fait" else "⏳"
                status_text_refresh = "Gedaan" if statut_refresh == "fait" else "In afwachting"
                
                global_idx_refresh = start_idx_refresh + idx
                message_refresh += f"**{global_idx_refresh}. {retour[3]}** {status_emoji_refresh}\n"
                message_refresh += f"📍 {retour[4]}\n"
                message_refresh += f"Status: {status_text_refresh}\n\n"
            
            message_refresh += f"_Totaal: {total_refresh} afwerking(en) - Pagina {current_page+1}/{total_pages_refresh}_"
            
            statut_keyboard_refresh = get_liste_statut_keyboard(retours_refresh, current_page, total_pages_refresh, current_chat_id)
            
            # Rafraîchir la liste en premier pour un feedback immédiat
            try:
                await query.edit_message_text(message_refresh, reply_markup=statut_keyboard_refresh, parse_mode='Markdown')
                await query.answer(f"✅ Status gewijzigd naar: {status_text}")
            except Exception as e:
                logger.error(f"Erreur rafraîchissement liste statut: {e}")
                await query.answer(f"✅ Status gewijzigd naar: {status_text}")
        
        # Ensuite, essayer de modifier le message dans le groupe (ne pas bloquer si ça échoue)
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id_retour,
                message_id=message_id,
                text=new_text,
                reply_markup=get_retour_keyboard(statut_final)
            )
        except Exception as e:
            # Ne pas bloquer si l'édition du message dans le groupe échoue
            # Le statut est déjà mis à jour dans la DB et la liste est déjà rafraîchie
            logger.warning(f"Impossible de modifier le message dans le groupe (peut-être supprimé): {e}")
    else:
        await query.answer("❌ Afwerking niet gevonden", show_alert=True)

async def voir_retours_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0) -> None:
    """Handler séparé pour le bouton 'Voir les retours' avec pagination"""
    query = update.callback_query
    await query.answer()
    
    if not check_authorization(update):
        return
    
    # Récupérer les retours paginés du groupe actuel depuis la base de données
    chat_id = query.message.chat_id
    retours, total, total_pages = get_retours_paginated(chat_id, page, per_page=10)
    
    if not retours:
        message = "📋 **Lijst van afwerkingen**\n\n"
        message += "Geen afwerkingen geregistreerd op dit moment."
        try:
            await query.edit_message_text(message, reply_markup=get_menu_keyboard(), parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Erreur édition message voir_retours: {e}")
            await query.message.reply_text(message, reply_markup=get_menu_keyboard(), parse_mode='Markdown')
        return
    
    # Formater la liste des retours de la page
    message = "📋 **Lijst van afwerkingen**\n\n"
    
    start_idx = page * 10 + 1
    for idx, retour in enumerate(retours):
        # retour est un tuple: (id, message_id, chat_id, nom_client, adresse, description, materiel, date, date_creation, statut)
        statut = get_statut_from_retour(retour)
        status_emoji = "✅" if statut == "fait" else "⏳"
        status_text = "Gedaan" if statut == "fait" else "In afwachting"
        
        # Récupérer et formater la date de création
        date_creation = retour[8] if len(retour) > 8 else None
        date_formatee = format_date_creation(date_creation)
        
        global_idx = start_idx + idx
        message += f"**{global_idx}. {retour[3]}** {status_emoji}\n"
        message += f"📍 {retour[4]}\n"
        message += f"🔧 {retour[5][:50]}{'...' if len(retour[5]) > 50 else ''}\n"
        message += f"📦 {retour[6]}\n"
        message += f"Status: {status_text}\n"
        message += f"📅 Gemaakt op: {date_formatee}\n\n"
    
    message += f"_Totaal: {total} afwerking(en) - Pagina {page+1}/{total_pages}_"
    
    # Clavier avec pagination
    pagination_keyboard = get_pagination_keyboard(page, total_pages)
    
    try:
        await query.edit_message_text(message, reply_markup=pagination_keyboard, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Erreur édition message voir_retours: {e}")
        await query.message.reply_text(message, reply_markup=pagination_keyboard, parse_mode='Markdown')

async def afwerken(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler pour la commande /afwerken"""
    if not check_authorization(update):
        return
    
    # Nettoyer les données et supprimer le message de statut s'il existe
    message_id = context.user_data.get('status_message_id')
    chat_id = context.user_data.get('status_chat_id')
    
    if message_id and chat_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        except ChatMigrated as e:
            # Le groupe a été migré, mettre à jour le chat_id et réessayer
            logger.info(f"Groupe migré vers supergroupe. Nouveau chat_id: {e.migrate_to_chat_id}")
            chat_id = e.migrate_to_chat_id
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
            except Exception:
                pass
        except Exception:
            pass  # Le message peut déjà être supprimé
    
    context.user_data.clear()
    
    message = "🔧 Afwerkingen beheer\n\n"
    message += "Kies een actie :"
    
    # Toujours répondre dans le groupe/conversation actuelle
    try:
        await update.message.reply_text(
            message,
            reply_markup=get_menu_keyboard()
        )
    except ChatMigrated as e:
        # Le groupe a été migré vers un supergroupe
        logger.info(f"Groupe migré vers supergroupe. Nouveau chat_id: {e.migrate_to_chat_id}")
        # Réessayer avec le nouveau chat_id
        await context.bot.send_message(
            chat_id=e.migrate_to_chat_id,
            text=message,
            reply_markup=get_menu_keyboard()
        )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler principal pour les boutons"""
    query = update.callback_query
    await query.answer()
    
    if not check_authorization(update):
        return ConversationHandler.END
    
    data = query.data
    
    if data == "ajouter_retour":
        # Créer un message éditable pour le formulaire
        context.user_data['retour'] = {}
        # Envoyer le message de statut dans le groupe
        chat_id = query.message.chat_id
        try:
            status_msg = await query.message.reply_text(
                "📝 **Afwerking toevoegen**\n\n📍 Adres : _In afwachting..._",
                reply_markup=get_cancel_keyboard(),
                parse_mode='Markdown'
            )
            chat_id = status_msg.chat_id  # Utiliser le chat_id du message envoyé (peut être différent après migration)
        except ChatMigrated as e:
            # Le groupe a été migré vers un supergroupe
            logger.info(f"Groupe migré vers supergroupe. Nouveau chat_id: {e.migrate_to_chat_id}")
            chat_id = e.migrate_to_chat_id
            # Réessayer avec le nouveau chat_id
            status_msg = await context.bot.send_message(
                chat_id=chat_id,
                text="📝 **Afwerking toevoegen**\n\n📍 Adres : _In afwachting..._",
                reply_markup=get_cancel_keyboard(),
                parse_mode='Markdown'
            )
        context.user_data['status_message_id'] = status_msg.message_id
        context.user_data['status_chat_id'] = chat_id  # Stocker chat_id pour le groupe
        await query.edit_message_reply_markup(reply_markup=None)  # Retirer les boutons temporairement
        await update_status_message(context, "📍 Adres :")
        return COLLECTING_ADRESSE
    
    elif data == "modifier_retour":
        message_id = query.message.message_id
        chat_id = query.message.chat_id
        
        # Récupérer les données depuis la base de données
        retour_db = get_retour_by_message_id(message_id, chat_id)
        if not retour_db:
            # Si pas dans la BDD, parser le message (rétrocompatibilité)
            message_text = query.message.text
            retour_data = parse_retour_message(message_text)
            statut = "en_attente"  # Par défaut si pas en BDD
        else:
            # retour_db: (id, message_id, chat_id, nom_client, adresse, description, materiel, date, date_creation, statut)
            retour_data = {
                'adresse': retour_db[4],
                'description': retour_db[5],
                'materiel': retour_db[6]
            }
            statut = get_statut_from_retour(retour_db)
        
        context.user_data['message_id_editing'] = message_id
        context.user_data['chat_id_editing'] = chat_id
        context.user_data['retour_data'] = retour_data
        context.user_data['statut_editing'] = statut
        
        await query.edit_message_reply_markup(reply_markup=get_modifier_keyboard())
        return SELECTING_ACTION
    
    elif data == "supprimer_retour":
        message_id = query.message.message_id
        chat_id = query.message.chat_id
        context.user_data['message_id_suppression'] = message_id
        context.user_data['chat_id_suppression'] = chat_id
        await query.edit_message_text(
            "⚠️ Bevestig verwijdering?",
            reply_markup=get_confirmation_keyboard()
        )
        return SELECTING_ACTION
    
    elif data == "modif_adresse":
        context.user_data['modif_type'] = 'adresse'
        await query.edit_message_text("✏️ Nieuw adres :")
        return MODIFYING_FIELD
    
    elif data == "modif_description":
        context.user_data['modif_type'] = 'description'
        await query.edit_message_text("✏️ Nieuwe beschrijving :")
        return MODIFYING_FIELD
    
    elif data == "modif_materiel":
        context.user_data['modif_type'] = 'materiel'
        await query.edit_message_text("✏️ Nieuw materiaal :")
        return MODIFYING_FIELD
    
    elif data == "annuler_modif":
        await query.edit_message_text("❌ Bewerking geannuleerd.", reply_markup=get_menu_keyboard())
        context.user_data.clear()
        return ConversationHandler.END
    
    elif data == "confirmer_suppression":
        message_id = context.user_data.get('message_id_suppression')
        chat_id = context.user_data.get('chat_id_suppression')
        if message_id and chat_id:
            try:
                # Supprimer de la base de données (seulement ce retour de ce groupe)
                delete_retour_from_db(message_id, chat_id)
                # Supprimer le message dans Telegram
                await context.bot.delete_message(
                    chat_id=chat_id,
                    message_id=message_id
                )
                await query.edit_message_text("✅ Afwerking verwijderd.", reply_markup=get_menu_keyboard())
            except Exception as e:
                logger.error(f"Erreur suppression message: {e}")
                await query.edit_message_text("❌ Fout bij het verwijderen.", reply_markup=get_menu_keyboard())
        context.user_data.clear()
        return ConversationHandler.END
    
    elif data == "annuler_suppression":
        await query.edit_message_text("❌ Verwijdering geannuleerd.", reply_markup=get_menu_keyboard())
        context.user_data.clear()
        return ConversationHandler.END
    
    
    elif data == "menu_principal":
        # Retour au menu principal
        welcome_text = "🤖 **Welkom bij de Afwerking Bot**\n\nKies een actie:"
        await query.edit_message_text(welcome_text, reply_markup=get_menu_keyboard(), parse_mode='Markdown')
        return ConversationHandler.END
    
    elif data == "noop":
        # Callback pour les boutons non-cliquables (ex: "Pagina X/Y")
        await query.answer()
        return SELECTING_ACTION
    
    return SELECTING_ACTION


async def collect_adresse(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Collecte l'adresse"""
    if not check_authorization(update):
        return ConversationHandler.END
    
    adresse = update.message.text.strip()
    context.user_data['retour']['adresse'] = adresse
    
    try:
        await update.message.delete()
    except Exception:
        pass
    
    # Passer directement au matériel, sans demander la description
    await update_status_message(context, "📦 Materiaal mee te nemen :")
    return COLLECTING_MATERIEL

async def collect_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Collecte la description"""
    if not check_authorization(update):
        return ConversationHandler.END
    
    description = update.message.text.strip()
    context.user_data['retour']['description'] = description
    
    try:
        await update.message.delete()
    except Exception:
        pass
    
    await update_status_message(context, "📦 Materiaal mee te nemen :")
    return COLLECTING_MATERIEL

async def collect_materiel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Collecte le matériel"""
    if not check_authorization(update):
        return ConversationHandler.END
    
    materiel = update.message.text.strip()
    context.user_data['retour']['materiel'] = materiel
    
    try:
        await update.message.delete()
    except Exception:
        pass
    
    # Demander "extra informatie" (optionnel) après le matériel
    await update_status_message(context, "ℹ️ Extra informatie (optioneel) :", show_skip=True)
    return COLLECTING_EXTRA_INFO

async def collect_extra_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Collecte l'information extra (optionnel) et finalise le retour"""
    if not check_authorization(update):
        return ConversationHandler.END
    
    # Vérifier si c'est un callback (bouton "Passer")
    if update.callback_query and update.callback_query.data == "passer_extra_info":
        extra_info = ""
        await update.callback_query.answer()
    else:
        extra_info = update.message.text.strip()
        if extra_info:
            context.user_data['retour']['extra_info'] = extra_info
        try:
            await update.message.delete()
        except Exception:
            pass
    
    # Supprimer le message de statut
    message_id = context.user_data.get('status_message_id')
    chat_id = context.user_data.get('status_chat_id')
    if message_id and chat_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception:
            pass
    
    # Publier le retour dans le groupe
    retour = context.user_data['retour']
    
    try:
        # Obtenir le chat_id du groupe depuis context ou depuis le message/callback
        group_chat_id = context.user_data.get('status_chat_id')
        if not group_chat_id:
            if update.message:
                group_chat_id = update.message.chat_id
            elif update.callback_query:
                group_chat_id = update.callback_query.message.chat_id
        
        if not group_chat_id:
            raise ValueError("Impossible de déterminer le chat_id du groupe")
        
        # Enregistrer dans la base de données d'abord
        try:
            temp_message = await context.bot.send_message(
                chat_id=group_chat_id,  # Dans le groupe
                text="⏳ Bezig met toevoegen...",
                reply_markup=get_retour_keyboard("en_attente")
            )
            group_chat_id = temp_message.chat_id  # Utiliser le chat_id du message envoyé
        except ChatMigrated as e:
            # Le groupe a été migré vers un supergroupe
            logger.info(f"Groupe migré vers supergroupe. Nouveau chat_id: {e.migrate_to_chat_id}")
            group_chat_id = e.migrate_to_chat_id
            # Réessayer avec le nouveau chat_id
            temp_message = await context.bot.send_message(
                chat_id=group_chat_id,
                text="⏳ Bezig met toevoegen...",
                reply_markup=get_retour_keyboard("en_attente")
            )
        
        extra_info_value = retour.get('extra_info', '')
        description_value = extra_info_value
        
        add_retour_to_db(
            temp_message.message_id,
            group_chat_id,
            "",  # nom vide maintenant
            retour['adresse'],
            description_value,
            retour['materiel'],
            "Non définie"
        )
        
        retour_db = get_retour_by_message_id(temp_message.message_id, group_chat_id)
        date_creation = retour_db[8] if retour_db and len(retour_db) > 8 else None
        
        message_text = format_retour_message(
            retour['adresse'],
            "",  # Description vide maintenant
            retour['materiel'],
            "en_attente",
            date_creation,
            extra_info_value
        )
        
        # Mettre à jour le message dans le groupe
        try:
            sent_message = await context.bot.edit_message_text(
                chat_id=group_chat_id,
                message_id=temp_message.message_id,
                text=message_text,
                reply_markup=get_retour_keyboard("en_attente")
            )
        except ChatMigrated as e:
            # Le groupe a été migré vers un supergroupe
            logger.info(f"Groupe migré vers supergroupe. Nouveau chat_id: {e.migrate_to_chat_id}")
            group_chat_id = e.migrate_to_chat_id
            # Mettre à jour le chat_id dans la base de données
            try:
                old_chat_id = context.user_data.get('status_chat_id')
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('UPDATE retours SET chat_id = ? WHERE message_id = ? AND chat_id = ?', 
                                 (group_chat_id, temp_message.message_id, old_chat_id))
                    conn.commit()
            except Exception as db_error:
                logger.warning(f"Erreur mise à jour chat_id dans BDD: {db_error}")
            # Réessayer avec le nouveau chat_id
            sent_message = await context.bot.edit_message_text(
                chat_id=group_chat_id,
                message_id=temp_message.message_id,
                text=message_text,
                reply_markup=get_retour_keyboard("en_attente")
            )
        
        # Envoyer la confirmation dans le groupe (utiliser send_message car le message peut avoir été supprimé)
        try:
            await context.bot.send_message(
                chat_id=group_chat_id,
                text="✅ Afwerking toegevoegd aan de groep.",
                reply_markup=get_menu_keyboard()
            )
        except ChatMigrated as e:
            # Le groupe a été migré vers un supergroupe
            logger.info(f"Groupe migré vers supergroupe. Nouveau chat_id: {e.migrate_to_chat_id}")
            await context.bot.send_message(
                chat_id=e.migrate_to_chat_id,
                text="✅ Afwerking toegevoegd aan de groep.",
                reply_markup=get_menu_keyboard()
            )
    except Exception as e:
        logger.error(f"Erreur envoi message: {e}")
        # Utiliser send_message au lieu de reply_text car le message peut avoir été supprimé
        try:
            group_chat_id = context.user_data.get('status_chat_id')
            if not group_chat_id:
                if update.message:
                    group_chat_id = update.message.chat_id
                elif update.callback_query:
                    group_chat_id = update.callback_query.message.chat_id
            if group_chat_id:
                await context.bot.send_message(
                    chat_id=group_chat_id,
                    text="❌ Fout bij het toevoegen van de afwerking.",
                    reply_markup=get_menu_keyboard()
                )
        except Exception as e2:
            logger.error(f"Erreur envoi message d'erreur: {e2}")
    
    context.user_data.clear()
    return ConversationHandler.END

async def handle_modification(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Gère la modification d'un champ"""
    if not check_authorization(update):
        return ConversationHandler.END
    
    new_value = update.message.text.strip()
    modif_type = context.user_data.get('modif_type')
    message_id = context.user_data.get('message_id_editing')
    chat_id = context.user_data.get('chat_id_editing')
    retour_data = context.user_data.get('retour_data', {})
    
    if not message_id or not chat_id or not retour_data:
        await update.message.reply_text(
            "❌ Fout: bewerkingsgegevens niet gevonden.",
            reply_markup=get_menu_keyboard()
        )
        context.user_data.clear()
        return ConversationHandler.END
    
    # Mapper le type de modification au nom de colonne dans la BDD
    field_mapping = {
        'adresse': 'adresse',
        'description': 'description',
        'materiel': 'materiel'
    }
    
    db_field = field_mapping.get(modif_type)
    if not db_field:
        await update.message.reply_text(
            "❌ Fout: ongeldig bewerkingstype.",
            reply_markup=get_menu_keyboard()
        )
        context.user_data.clear()
        return ConversationHandler.END
    
    # Mettre à jour dans la base de données
    update_retour_in_db(message_id, chat_id, db_field, new_value)
    
    # Récupérer toutes les données mises à jour depuis la BDD
    retour_db = get_retour_by_message_id(message_id, chat_id)
    if retour_db:
        # retour_db: (id, message_id, chat_id, nom_client, adresse, description, materiel, date, date_creation, statut)
        adresse = retour_db[4]
        description = retour_db[5]
        materiel = retour_db[6]
        date_creation = retour_db[8] if len(retour_db) > 8 else None
        statut_actuel = get_statut_from_retour(retour_db)
    else:
        # Fallback sur les données locales si la BDD échoue
        if modif_type == 'adresse':
            retour_data['adresse'] = new_value
        elif modif_type == 'description':
            retour_data['description'] = new_value
        elif modif_type == 'materiel':
            retour_data['materiel'] = new_value
        
        adresse = retour_data.get('adresse', 'N/A')
        description = retour_data.get('description', 'N/A')
        materiel = retour_data.get('materiel', 'N/A')
        date_creation = None
        statut_actuel = "en_attente"
    
    try:
        # Utiliser description comme extra_info si présent
        extra_info = description if description and description != 'N/A' else None
        new_text = format_retour_message(adresse, "", materiel, statut_actuel, date_creation, extra_info)
        
        # Éditer le message dans le groupe (utiliser le chat_id stocké)
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=new_text,
            reply_markup=get_retour_keyboard(statut_actuel)
        )
        
        # Confirmer à l'utilisateur dans le groupe
        field_names = {
            'adresse': 'Adres',
            'description': 'Beschrijving',
            'materiel': 'Materiaal'
        }
        field_name = field_names.get(modif_type, 'Veld')
        await update.message.reply_text(
            f"✅ {field_name} bijgewerkt.",
            reply_markup=get_menu_keyboard()
        )
    except Exception as e:
        logger.error(f"Erreur modification: {e}")
        await update.message.reply_text(
            "❌ Fout bij het bewerken.",
            reply_markup=get_menu_keyboard()
        )
    
    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Annule la conversation"""
    if not check_authorization(update):
        return ConversationHandler.END
    
    context.user_data.clear()
    await update.message.reply_text(
        "❌ Operatie geannuleerd.",
        reply_markup=get_menu_keyboard()
    )
    return ConversationHandler.END

# ==================== MAIN ====================

def main() -> None:
    """Fonction principale"""
    # Initialiser la base de données
    init_database()
    logger.info(f"Base de données initialisée: {DB_NAME}")
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    # ConversationHandler pour la gestion des retours
    # conversation_timeout: expire automatiquement après 10 minutes d'inactivité
    # Cela évite l'accumulation de données dans user_data et libère les ressources
    conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(button_handler, pattern="^ajouter_retour$"),
            CallbackQueryHandler(button_handler, pattern="^modifier_retour$"),
            CallbackQueryHandler(button_handler, pattern="^supprimer_retour$"),
            CallbackQueryHandler(button_handler, pattern="^modif_"),
            CallbackQueryHandler(button_handler, pattern="^(confirmer|annuler)_")
        ],
        states={
            SELECTING_ACTION: [CallbackQueryHandler(button_handler)],
            COLLECTING_ADRESSE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, collect_adresse)
            ],
            COLLECTING_DESCRIPTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, collect_description)
            ],
            COLLECTING_MATERIEL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, collect_materiel)
            ],
            COLLECTING_EXTRA_INFO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, collect_extra_info),
                CallbackQueryHandler(collect_extra_info, pattern="^passer_extra_info$")
            ],
            MODIFYING_FIELD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_modification)
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("afwerken", afwerken)
        ],
        allow_reentry=True,
        conversation_timeout=600.0  # 10 minutes d'inactivité = expiration automatique
    )
    
    # Handler d'erreurs global
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Gère les erreurs non capturées"""
        error = context.error
        
        # Gérer spécifiquement les migrations de groupe
        if isinstance(error, ChatMigrated):
            logger.info(f"Groupe migré vers supergroupe. Nouveau chat_id: {error.migrate_to_chat_id}")
            # Ne pas logger comme une erreur, c'est normal
            return
        
        logger.error(f"Exception while handling an update: {error}", exc_info=error)
        
        # Essayer d'envoyer un message d'erreur à l'utilisateur si possible
        if isinstance(update, Update) and update.effective_message:
            try:
                error_message = "❌ Er is een fout opgetreden. Probeer het later opnieuw."
                await update.effective_message.reply_text(error_message)
            except ChatMigrated as e:
                # Le groupe a été migré, essayer avec le nouveau chat_id
                try:
                    await context.bot.send_message(
                        chat_id=e.migrate_to_chat_id,
                        text=error_message
                    )
                except Exception:
                    pass
            except Exception:
                # Si on ne peut pas envoyer de message, on log juste l'erreur
                pass
    
    application.add_handler(CommandHandler("afwerken", afwerken))
    # Handler séparé pour "noop" (boutons non-cliquables, doit être avant ConversationHandler)
    async def noop_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if query:
            await query.answer()
    application.add_handler(CallbackQueryHandler(noop_handler, pattern="^noop$"))
    # Handler séparé pour "annuler_ajout" (doit être avant le ConversationHandler)
    application.add_handler(CallbackQueryHandler(annuler_ajout_handler, pattern="^annuler_ajout$"))
    # Handler séparé pour changer le statut (doit être avant le ConversationHandler)
    application.add_handler(CallbackQueryHandler(statut_handler, pattern="^(statut_fait|statut_attente)$"))
    # Handler séparé pour "menu_principal" (doit être avant le ConversationHandler)
    application.add_handler(CallbackQueryHandler(menu_principal_handler, pattern="^menu_principal$"))
    # Handler séparé pour "voir_retours" (doit être avant le ConversationHandler)
    application.add_handler(CallbackQueryHandler(lambda u, c: voir_retours_handler(u, c, 0), pattern="^voir_retours$"))
    # Handler pour la pagination
    application.add_handler(CallbackQueryHandler(voir_retours_page_handler, pattern="^voir_retours_page_"))
    # Handler séparé pour "changer_statut" (doit être avant le ConversationHandler)
    application.add_handler(CallbackQueryHandler(lambda u, c: changer_statut_handler(u, c, 0), pattern="^changer_statut$"))
    # Handler pour la pagination de changer_statut
    application.add_handler(CallbackQueryHandler(changer_statut_page_handler, pattern="^changer_statut_page_"))
    # Handler pour sélectionner un retour et changer son statut
    application.add_handler(CallbackQueryHandler(changer_statut_select_handler, pattern="^changer_statut_select_"))
    application.add_handler(conv_handler)
    
    # Ajouter le handler d'erreurs global (doit être le dernier)
    application.add_error_handler(error_handler)
    
    logger.info("Bot démarré")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()