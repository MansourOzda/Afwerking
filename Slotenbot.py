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
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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
DB_NAME = "retours_intervention.db"

# ==================== BASE DE DONNÉES ====================

def init_database():
    """Initialise la base de données SQLite"""
    conn = sqlite3.connect(DB_NAME)
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
    # Ajouter la colonne chat_id si elle n'existe pas (migration pour bases existantes)
    try:
        cursor.execute('ALTER TABLE retours ADD COLUMN chat_id INTEGER')
        conn.commit()
    except sqlite3.OperationalError:
        # La colonne existe déjà, pas de problème
        pass
    conn.commit()
    conn.close()

def add_retour_to_db(message_id: int, chat_id: int, nom: str, adresse: str, description: str, materiel: str, date: str):
    """Ajoute un retour à la base de données"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO retours (message_id, chat_id, nom_client, adresse, description, materiel, date)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (message_id, chat_id, nom, adresse, description, materiel, date))
    conn.commit()
    conn.close()

def update_retour_in_db(message_id: int, chat_id: int, field: str, value: str):
    """Met à jour un champ d'un retour dans la base de données (spécifique au groupe)"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(f'UPDATE retours SET {field} = ? WHERE message_id = ? AND chat_id = ?', (value, message_id, chat_id))
    conn.commit()
    conn.close()

def delete_retour_from_db(message_id: int, chat_id: int):
    """Supprime un retour de la base de données (spécifique au groupe)"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM retours WHERE message_id = ? AND chat_id = ?', (message_id, chat_id))
    conn.commit()
    conn.close()

def get_all_retours(chat_id: int) -> List[Tuple]:
    """Récupère tous les retours d'un groupe spécifique"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM retours WHERE chat_id = ? ORDER BY date_creation DESC', (chat_id,))
    retours = cursor.fetchall()
    conn.close()
    return retours

def get_retour_by_message_id(message_id: int, chat_id: int) -> Optional[Tuple]:
    """Récupère un retour par son message_id et chat_id"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM retours WHERE message_id = ? AND chat_id = ?', (message_id, chat_id))
    retour = cursor.fetchone()
    conn.close()
    return retour

# ==================== CONSTANTES ====================

# États pour ConversationHandler
(SELECTING_ACTION,
 COLLECTING_NOM_CLIENT,
 COLLECTING_ADRESSE,
 COLLECTING_DESCRIPTION,
 COLLECTING_MATERIEL,
 COLLECTING_DATE,
 MODIFYING_FIELD) = range(7)

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

def format_retour_message(nom: str, adresse: str, description: str, 
                         materiel: str) -> str:
    """Formate le message de retour d'intervention"""
    message = "🔁 AFWERKING\n\n"
    message += f"Klant : {nom}\n"
    message += f"Adres : {adresse}\n"
    message += f"Te doen : {description}\n"
    message += f"Materiaal : {materiel}"
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
                data['description'] = line.replace('Te doen :', '').strip()
            elif line.startswith('Materiaal :'):
                data['materiel'] = line.replace('Materiaal :', '').strip()
    except Exception as e:
        logger.error(f"Erreur parsing message: {e}")
    return data

def get_retour_keyboard() -> InlineKeyboardMarkup:
    """Retourne le clavier pour un retour (modifier/supprimer)"""
    keyboard = [
        [InlineKeyboardButton("✏️ Bewerken", callback_data="modifier_retour")],
        [InlineKeyboardButton("🗑 Verwijderen", callback_data="supprimer_retour")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_menu_keyboard() -> InlineKeyboardMarkup:
    """Retourne le clavier du menu principal"""
    keyboard = [
        [InlineKeyboardButton("➕ Afwerking toevoegen", callback_data="ajouter_retour")],
        [InlineKeyboardButton("📋 Zie afwerking", callback_data="voir_retours")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_modifier_keyboard() -> InlineKeyboardMarkup:
    """Retourne le clavier pour modifier un retour"""
    keyboard = [
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

# ==================== HANDLERS ====================

async def update_status_message(context: ContextTypes.DEFAULT_TYPE, current_question: str):
    """Met à jour le message de statut avec les réponses déjà données"""
    retour = context.user_data.get('retour', {})
    message_id = context.user_data.get('status_message_id')
    chat_id = context.user_data.get('status_chat_id')
    
    if not message_id or not chat_id:
        return
    
    status_text = "📝 **Afwerking toevoegen**\n\n"
    
    if retour.get('nom'):
        status_text += f"👤 Naam van klant : {retour['nom']}\n"
    else:
        status_text += "👤 Naam van klant : _In afwachting..._\n"
    
    if retour.get('adresse'):
        status_text += f"📍 Adres : {retour['adresse']}\n"
    elif 'nom' in retour:
        status_text += "📍 Adres : _In afwachting..._\n"
    
    if retour.get('description'):
        status_text += f"🔧 Beschrijving : {retour['description']}\n"
    elif 'adresse' in retour:
        status_text += "🔧 Beschrijving : _In afwachting..._\n"
    
    if retour.get('materiel'):
        status_text += f"📦 Materiaal : {retour['materiel']}\n"
    elif 'description' in retour:
        status_text += "📦 Materiaal : _In afwachting..._\n"
    
    status_text += f"\n💬 {current_question}"
    
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=status_text,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Erreur mise à jour message statut: {e}")

async def voir_retours_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler séparé pour le bouton 'Voir les retours'"""
    query = update.callback_query
    await query.answer()
    
    if not check_authorization(update):
        return
    
    # Récupérer tous les retours du groupe actuel depuis la base de données
    chat_id = query.message.chat_id
    retours = get_all_retours(chat_id)
    
    if not retours:
        message = "📋 **Lijst van afwerkingen**\n\n"
        message += "Geen afwerkingen geregistreerd op dit moment."
        try:
            await query.edit_message_text(message, reply_markup=get_menu_keyboard(), parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Erreur édition message voir_retours: {e}")
            await query.message.reply_text(message, reply_markup=get_menu_keyboard(), parse_mode='Markdown')
        return
    
    # Formater la liste des retours
    message = "📋 **Lijst van afwerkingen**\n\n"
    
    for idx, retour in enumerate(retours, 1):
        # retour est un tuple: (id, message_id, chat_id, nom_client, adresse, description, materiel, date, date_creation)
        message += f"**{idx}. {retour[3]}**\n"
        message += f"📍 {retour[4]}\n"
        message += f"🔧 {retour[5][:50]}{'...' if len(retour[5]) > 50 else ''}\n"
        message += f"📦 {retour[6]}\n\n"
    
    message += f"_Totaal: {len(retours)} afwerking(en)_"
    
    # Si le message est trop long, le diviser en plusieurs messages
    if len(message) > 4000:  # Limite Telegram ~4096 caractères
        # Envoyer le premier message avec les premiers retours
        first_part = "📋 **Lijst van afwerkingen**\n\n"
        remaining_chars = 4000 - len(first_part) - 100  # Marge de sécurité
        
        current_msg = first_part
        for idx, retour in enumerate(retours, 1):
            retour_text = f"**{idx}. {retour[3]}**\n📍 {retour[4]}\n🔧 {retour[5][:50]}{'...' if len(retour[5]) > 50 else ''}\n📦 {retour[6]}\n\n"
            if len(current_msg) + len(retour_text) > remaining_chars:
                break
            current_msg += retour_text
        
        try:
            await query.edit_message_text(current_msg, reply_markup=get_menu_keyboard(), parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Erreur édition message voir_retours: {e}")
            await query.message.reply_text(current_msg, reply_markup=get_menu_keyboard(), parse_mode='Markdown')
    else:
        try:
            await query.edit_message_text(message, reply_markup=get_menu_keyboard(), parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Erreur édition message voir_retours: {e}")
            await query.message.reply_text(message, reply_markup=get_menu_keyboard(), parse_mode='Markdown')

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler pour la commande /start"""
    if not check_authorization(update):
        return
    
    context.user_data.clear()
    
    message = "🔧 Gestion des retours d'intervention\n\n"
    message += "Choisissez une action :"
    
    await update.message.reply_text(
        message,
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
        status_msg = await query.message.reply_text(
            "📝 **Ajout d'un retour**\n\n👤 Nom du client : _En attente..._",
            parse_mode='Markdown'
        )
        context.user_data['retour'] = {}
        context.user_data['status_message_id'] = status_msg.message_id
        context.user_data['status_chat_id'] = status_msg.chat_id
        await query.edit_message_reply_markup(reply_markup=None)  # Retirer les boutons temporairement
        await update_status_message(context, "👤 Nom du client :")
        return COLLECTING_NOM_CLIENT
    
    elif data == "modifier_retour":
        message_id = query.message.message_id
        chat_id = query.message.chat_id
        
        # Récupérer les données depuis la base de données
        retour_db = get_retour_by_message_id(message_id, chat_id)
        if not retour_db:
            # Si pas dans la BDD, parser le message (rétrocompatibilité)
            message_text = query.message.text
            retour_data = parse_retour_message(message_text)
        else:
            # retour_db: (id, message_id, chat_id, nom_client, adresse, description, materiel, date, date_creation)
            retour_data = {
                'nom': retour_db[3],
                'adresse': retour_db[4],
                'description': retour_db[5],
                'materiel': retour_db[6]
            }
        
        context.user_data['message_id_editing'] = message_id
        context.user_data['chat_id_editing'] = chat_id
        context.user_data['retour_data'] = retour_data
        
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
    
    return SELECTING_ACTION

async def collect_nom_client(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Collecte le nom du client"""
    if not check_authorization(update):
        return ConversationHandler.END
    
    nom = update.message.text.strip()
    context.user_data['retour']['nom'] = nom
    
    # Supprimer le message de réponse de l'utilisateur pour réduire l'encombrement
    try:
        await update.message.delete()
    except Exception:
        pass
    
    # Mettre à jour le message de statut
    await update_status_message(context, "📍 Adres :")
    return COLLECTING_ADRESSE

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
    
    await update_status_message(context, "🔧 Beschrijving van het werk te doen :")
    return COLLECTING_DESCRIPTION

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
    """Collecte le matériel et finalise le retour"""
    if not check_authorization(update):
        return ConversationHandler.END
    
    materiel = update.message.text.strip()
    context.user_data['retour']['materiel'] = materiel
    
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
    message_text = format_retour_message(
        retour['nom'],
        retour['adresse'],
        retour['description'],
        retour['materiel']
    )
    
    try:
        # Utiliser le chat_id du message actuel (n'importe quel groupe)
        chat_id = update.message.chat_id
        sent_message = await context.bot.send_message(
            chat_id=chat_id,
            text=message_text,
            reply_markup=get_retour_keyboard()
        )
        # Enregistrer dans la base de données (date = "Non définie" pour compatibilité)
        add_retour_to_db(
            sent_message.message_id,
            chat_id,  # Stocker le chat_id pour séparer par groupe
            retour['nom'],
            retour['adresse'],
            retour['description'],
            retour['materiel'],
            "Non définie"
        )
        await context.bot.send_message(
            chat_id=update.message.chat_id,
            text="✅ Afwerking toegevoegd aan de groep.",
            reply_markup=get_menu_keyboard()
        )
    except Exception as e:
        logger.error(f"Erreur envoi message: {e}")
        await context.bot.send_message(
            chat_id=update.message.chat_id,
            text="❌ Fout bij het toevoegen van de afwerking.",
            reply_markup=get_menu_keyboard()
        )
    
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
        await update.message.reply_text("❌ Fout: bewerkingsgegevens niet gevonden.", reply_markup=get_menu_keyboard())
        context.user_data.clear()
        return ConversationHandler.END
    
    # Mapper le type de modification au nom de colonne dans la BDD
    field_mapping = {
        'description': 'description',
        'materiel': 'materiel'
    }
    
    db_field = field_mapping.get(modif_type)
    if not db_field:
        await update.message.reply_text("❌ Fout: ongeldig bewerkingstype.", reply_markup=get_menu_keyboard())
        context.user_data.clear()
        return ConversationHandler.END
    
    # Mettre à jour dans la base de données
    update_retour_in_db(message_id, chat_id, db_field, new_value)
    
    # Récupérer toutes les données mises à jour depuis la BDD
    retour_db = get_retour_by_message_id(message_id, chat_id)
    if retour_db:
        # retour_db: (id, message_id, chat_id, nom_client, adresse, description, materiel, date, date_creation)
        nom = retour_db[3]
        adresse = retour_db[4]
        description = retour_db[5]
        materiel = retour_db[6]
    else:
        # Fallback sur les données locales si la BDD échoue
        if modif_type == 'description':
            retour_data['description'] = new_value
        elif modif_type == 'materiel':
            retour_data['materiel'] = new_value
        
        nom = retour_data.get('nom', 'N/A')
        adresse = retour_data.get('adresse', 'N/A')
        description = retour_data.get('description', 'N/A')
        materiel = retour_data.get('materiel', 'N/A')
    
    new_text = format_retour_message(nom, adresse, description, materiel)
    
    try:
        # Éditer le message dans le groupe (utiliser le chat_id stocké)
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=new_text,
            reply_markup=get_retour_keyboard()
        )
        
        # Confirmer à l'utilisateur
        field_names = {'description': 'Beschrijving', 'materiel': 'Materiaal'}
        field_name = field_names.get(modif_type, 'Veld')
        await update.message.reply_text(f"✅ {field_name} bijgewerkt.", reply_markup=get_menu_keyboard())
    except Exception as e:
        logger.error(f"Erreur modification: {e}")
        await update.message.reply_text("❌ Fout bij het bewerken.", reply_markup=get_menu_keyboard())
    
    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Annule la conversation"""
    if not check_authorization(update):
        return ConversationHandler.END
    
    context.user_data.clear()
    await update.message.reply_text("❌ Operatie geannuleerd.", reply_markup=get_menu_keyboard())
    return ConversationHandler.END

# ==================== MAIN ====================

def main() -> None:
    """Fonction principale"""
    # Initialiser la base de données
    init_database()
    logger.info(f"Base de données initialisée: {DB_NAME}")
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    # ConversationHandler pour la gestion des retours
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
            COLLECTING_NOM_CLIENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, collect_nom_client)
            ],
            COLLECTING_ADRESSE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, collect_adresse)
            ],
            COLLECTING_DESCRIPTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, collect_description)
            ],
            COLLECTING_MATERIEL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, collect_materiel)
            ],
            MODIFYING_FIELD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_modification)
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("start", start)
        ],
        allow_reentry=True
    )
    
    application.add_handler(CommandHandler("start", start))
    # Handler séparé pour "voir_retours" (doit être avant le ConversationHandler)
    application.add_handler(CallbackQueryHandler(voir_retours_handler, pattern="^voir_retours$"))
    application.add_handler(conv_handler)
    
    logger.info("Bot démarré")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()