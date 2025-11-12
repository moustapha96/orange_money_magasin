


from odoo import http, fields
from odoo.http import request
import json
import logging
from datetime import datetime

_logger = logging.getLogger(__name__)

class OrangeMoneyWebhookController(http.Controller):
    """
    Contrôleur pour gérer les webhooks Orange Money
    """

    
    @http.route('/orange/webhook', type='json', auth='public', csrf=False, methods=['POST'])
    def orange_webhook(self, **payload):
        """
        Endpoint pour recevoir et traiter les notifications webhook Orange Money
        """
        try:
            data = json.loads(request.httprequest.data)
            _logger.info("Webhook Orange Money reçu Request : %s", request.httprequest)
            _logger.info("Webhook Orange Money reçu response http header : %s", request.httprequest.headers)
            _logger.info(f"Webhook Orange Money reçu : {data}")

            # Extraction des données principales
            amount = data.get('amount', {})
            customer = data.get('customer', {})
            customerIdType = customer.get('idType')
            customerId = customer.get('id')
            _logger.info(f'customer : {customer}')
            partner = data.get('partner', {})
            partnerIdType = partner.get('idType')
            partnerId = partner.get('id')
            _logger.info(f'partner : {partner}')
            channel = data.get('channel')
            payment_method = data.get('paymentMethod')
            status = data.get('status').upper()
            orange_transaction_id = data.get('transactionId')
            type_payment = data.get('type')
            metadata = data.get('metadata', {})
            _logger.info(f"channel : {channel}, payment_method : {payment_method}, status : {status}, orange_transaction_id : {orange_transaction_id}, type_payment : {type_payment}")
            _logger.info(f"metadata : {metadata}")
            _logger.info(f"data  {data}")

            # Gestion des métadonnées (JSON string ou dict)
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except json.JSONDecodeError:
                    _logger.error("Erreur de décodage JSON dans les métadonnées")
                    return {'status': 'error', 'message': 'Erreur de décodage JSON dans les métadonnées'}

            transaction_id = metadata.get('transaction_id', '')

            # Recherche de la transaction dans Odoo
            transaction_om = request.env['orange.money.transaction'].sudo().search([('transaction_id', '=', transaction_id)], limit=1)
            _logger.info(f"Transaction trouvée : {transaction_om}")
            _logger.info(f"Transaction ID : {transaction_id}, Orange Transaction ID : {orange_transaction_id}, Status : {status}")

            if not transaction_om:
                _logger.error(f"Transaction non trouvée pour transaction_id : {transaction_id}")
                return {'status': 'error', 'message': 'Transaction non trouvée'}

            # Mapping et mise à jour du statut si nécessaire
            odoo_status = self._map_orange_status_to_odoo(status)
            if odoo_status and transaction_om:
                _logger.info(f"Mise à jour du statut de la transaction {transaction_id} à {odoo_status}")
                transaction_om.write({
                    'status': odoo_status,
                    'updated_at': fields.Datetime.now(),
                    'webhook_data': json.dumps(data),
                    'transactionId': orange_transaction_id,
                    'channel': channel or '',
                    'payment_method': payment_method or '',
                    'transaction_type': type_payment or '',
                    'partnerId': partnerId or '',
                    'partnerId_type': partnerIdType or '',
                    'customer_id': customerId or '',
                    'customer_id_type': customerIdType or '',
                })

                # Si le statut est 'SUCCESS', créer le paiement et le réconcilier avec la facture
                if status == 'SUCCESS':
                    # Créer le paiement et le réconcilier avec la facture
                    payment_result = self.process_payment(transaction_om.account_move_id, transaction_om.amount, request.env.company)
                    if not payment_result['success']:
                        _logger.error(f"Erreur lors du traitement du paiement pour la transaction {transaction_id}")
                        return {'status': 'error', 'message': 'Erreur lors du traitement du paiement'}

            return {'status': 'success', 'message': 'Transaction mise à jour avec succès'}
        except Exception as e:
            _logger.error(f"Erreur lors du traitement du webhook Orange Money : {str(e)}")
            return {'status': 'error', 'message': f'Erreur interne du serveur : {str(e)}'}



    def _map_orange_status_to_odoo(self, orange_status):
        """Mapper les statuts Orange Money vers les statuts Odoo"""
        status_mapping = {
            'SUCCESS': 'SUCCESS',
            'SUCCEEDED': 'SUCCESS',
            'FAILED': 'FAILED',
            'PENDING': 'PENDING',
            'PROCESSING': 'PENDING',
            'EXPIRED': 'FAILED', # Mapping EXPIRED to FAILED for Odoo status
            'CANCELLED': 'CANCELLED',
            'CANCELED': 'CANCELLED',
            'REJECTED': 'REJECTED', # Added REJECTED
        }
        return status_mapping.get(orange_status.upper(), 'PENDING')


    def _create_payment_without_invoice(self, transaction):
        """Créer un paiement sans facture pour une transaction Orange Money réussie"""
        try:
            _logger.info(f"Début de la création du paiement et de la facture pour la transaction {transaction.transaction_id}")
            order = transaction.order_id
            partner = transaction.partner_id
            company = partner.company_id or request.env['res.company'].sudo().search([('id', '=', 1)], limit=1)
            _logger.info(f"Compagnie trouvée: {company.name}")

            journal = request.env['account.journal'].sudo().search([('code', '=', 'CSH1'), ('company_id', '=', company.id)], limit=1)
            if not journal:
                _logger.error("Aucun journal de vente trouvé pour la compagnie.")
                return False

            _logger.info(f"Journal trouvé: {journal.name}")

            payment_method = request.env['account.payment.method'].sudo().search([('payment_type', '=', 'inbound')], limit=1)
            if not payment_method:
                _logger.error("Aucune méthode de paiement trouvée.")
                return False

            _logger.info(f"Méthode de paiement trouvée: {payment_method.name}")

            payment_method_line = request.env['account.payment.method.line'].sudo().search([
                ('payment_method_id', '=', payment_method.id),
                ('journal_id', '=', journal.id)
            ], limit=1)
            if not payment_method_line:
                _logger.error("Aucune ligne de méthode de paiement trouvée.")
                return False

            _logger.info(f"Ligne de méthode de paiement trouvée: {payment_method_line.id}")

            if order and order.state not in ['sale', 'done']:
                _logger.info(f"Confirmation de la commande {order.name}")
                order.action_confirm()


            currency_id = partner.currency_id.id or order.currency_id.id or journal.currency_id.id
            if not currency_id:
                _logger.error("Aucune devise trouvée pour la facture.")
                return False


            if order.amount_residual > 0:
                _logger.info(f"Création du paiement pour la commande {order.name}")
                account_payment = request.env['account.payment'].sudo().create({
                    'payment_type': 'inbound',
                    'partner_type': 'customer',
                    'partner_id': partner.id,
                    'amount': transaction.amount,
                    'journal_id': journal.id,
                    'currency_id': currency_id,
                    'payment_method_line_id': payment_method_line.id,
                    'payment_method_id': payment_method.id,
                    'ref': order.name,
                    'sale_id': order.id,
                    'is_reconciled': True,
                    'destination_account_id': partner.property_account_receivable_id.id,
                })
                account_payment.action_post()
                _logger.info(f"Paiement créé et validé pour la commande {order.name}")
            else:
                _logger.warning(f"Le montant résiduel de la commande {order.name} est de 0, aucun paiement créé.")

            _logger.info(f"Paiement et facture créés avec succès pour la transaction Orange Money {transaction.transaction_id}")
            return True
        except Exception as e:
            _logger.error(f"Erreur lors de la création du paiement Orange Money: {str(e)}")
            return False
    

    def process_payment(self, invoice, amount, company):
        """
        Traite le paiement pour la facture existante
        Args:
            invoice: Facture existante (account.move)
            amount: Montant du paiement
            company: Société
        Returns:
            dict: Résultat du traitement
        """
        try:
            # Récupérer le journal de paiement
            journal = request.env['account.journal'].sudo().search([
                ('code', '=', 'CSH1'),
                ('company_id', '=', company.id)
            ], limit=1)
            if not journal:
                journal = request.env['account.journal'].sudo().search([
                    ('type', 'in', ['cash', 'bank']),
                    ('company_id', '=', company.id)
                ], limit=1)

            if not journal:
                return {'success': False, 'error': 'Aucun journal de paiement trouvé'}

            # Récupérer une méthode de paiement
            payment_method = request.env['account.payment.method'].sudo().search([('payment_type', '=', 'inbound')], limit=1)
            if not payment_method:
                return {'success': False, 'error': 'Aucune méthode de paiement trouvée'}

            # Créer le paiement
            payment = self._register_payment(invoice, amount, journal.id, payment_method.id)
            if not payment:
                return {'success': False, 'error': 'Erreur lors de l\'enregistrement du paiement'}

            # Réconcilier le paiement avec la facture
            self._reconcile_payment_with_invoice(payment, invoice)

            return {
                'success': True,
                'payment_id': payment.id,
                'invoice_id': invoice.id,
                'amount': amount,
                'message': 'Paiement enregistré et réconcilié avec succès'
            }
        except Exception as e:
            _logger.error(f"Erreur lors du traitement du paiement: {str(e)}")
            return {'success': False, 'error': str(e)}



    def _register_payment(self, invoice, amount, journal_id, payment_method_id=None):
        """
        Enregistre un paiement sur la facture existante.
        Args:
            invoice: Facture existante (account.move)
            amount: Montant du paiement
            journal_id: ID du journal (ex: banque)
            payment_method_id: ID de la méthode de paiement
        Returns:
            account.payment
        """
        try:
            payment = request.env['account.payment'].create({
                'payment_type': 'inbound',
                'partner_type': 'customer',
                'partner_id': invoice.partner_id.id,
                'amount': amount,
                'journal_id': journal_id,
                'payment_method_id': payment_method_id,
                'ref': f"Paiement Orange Money - {invoice.name}",
            })

            # Valider le paiement
            payment.action_post()

            return payment
        except Exception as e:
            _logger.error(f"Erreur lors de l'enregistrement du paiement: {str(e)}")
            return None

        

    def _reconcile_payment_with_invoice(self, payment, invoice):
        """
        Réconcilie le paiement avec la facture
        
        Args:
            payment: Objet account.payment
            invoice: Objet account.move
        """
        try:
            # Récupérer les lignes à réconcilier
            invoice_lines = invoice.line_ids.filtered(
                lambda line: line.account_id.account_type == 'asset_receivable' and not line.reconciled
            )
            # Si la version d'Odoo est antérieure à 15.0, utiliser account_internal_type au lieu de account_type
            if not invoice_lines:
                invoice_lines = invoice.line_ids.filtered(
                    lambda line: line.account_id.internal_type == 'receivable' and not line.reconciled
                )
            
            payment_lines = payment.move_id.line_ids.filtered(
                lambda line: line.account_id.account_type == 'asset_receivable'
            )
            # Si la version d'Odoo est antérieure à 15.0, utiliser account_internal_type au lieu de account_type
            if not payment_lines:
                payment_lines = payment.move_id.line_ids.filtered(
                    lambda line: line.account_id.internal_type == 'receivable'
                )
            # Réconcilier
            lines_to_reconcile = invoice_lines + payment_lines
            if lines_to_reconcile:
                lines_to_reconcile.reconcile()
                _logger.info("Paiement %s réconcilié avec facture d'acompte %s", payment.name, invoice.name)
            else:
                _logger.warning("Aucune ligne à réconcilier trouvée pour le paiement %s et la facture %s", 
                        payment.name, invoice.name)
                
        except Exception as e:
            _logger.exception("Erreur lors de la réconciliation du paiement: %s", str(e))
            return None

